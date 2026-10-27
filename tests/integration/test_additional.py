from io import BytesIO
import pytest
from app.models.domain import Intervention,Certificate,Document,Contract
from app.extensions import db
from .test_obras_flows import request,work,upload,cert_new,approve
from app.services.reports import pdf_report
from app.demo import seed
from app.services.importing import preview
import openpyxl

def test_seed_idempotent_and_roles_scope(client,login,app):
    with app.app_context():
        before=(Intervention.query.count(),Document.query.count())
        seed(with_certificates=False)
        assert before==(Intervention.query.count(),Document.query.count())
    w=request(client,login,'admin','post','/works',{'name':'Obra fuera del equipo','description':'Privada','locality':'Minas'},201)['work']
    assert client.get(f"/api/works/{w['id']}",headers=login('tecnico')).status_code==404
    assert client.post(f"/api/works/{w['id']}/records",headers=login('consulta'),json={'kind':'tarea','title':'No autorizado'}).status_code==403

def test_reset_guard_and_preserves_non_seed_work(client,login,app):
    own=request(client,login,'admin','post','/works',{'name':'Debe sobrevivir al reset','description':'Creada por usuario','locality':'Minas'},201)['work']
    runner=app.test_cli_runner()
    rejected=runner.invoke(args=['reset-demo','--confirm-database','obras_demo'])
    assert rejected.exit_code!=0
    with app.app_context():
        before=Intervention.query.count()
        assert db.session.get(Intervention,own['id']) is not None
    accepted=runner.invoke(args=['reset-demo','--confirm-database','obras_test'])
    assert accepted.exit_code==0,accepted.output
    with app.app_context():
        assert Intervention.query.count()==before
        assert db.session.get(Intervention,own['id']).demo is False
    app.config['DEMO_ENVIRONMENT']=False
    try:
        assert runner.invoke(args=['reset-demo','--confirm-database','obras_test']).exit_code!=0
    finally:
        app.config['DEMO_ENVIRONMENT']=True

def test_classification_and_suspended_company_temporary_link(client,login):
    w=work(client,login,'DEMO-MOLINO')
    d=upload(client,login,w['id'],'admin','confidencial.txt','informe',b'Contenido confidencial',classification='confidencial')
    assert client.get(f"/api/documents/{d['id']}/download",headers=login('director')).status_code==404
    assert client.get(f"/api/documents/{d['id']}/download",headers=login('empresa-a')).status_code==404
    assert client.get(f"/api/documents/{d['id']}/download",headers=login('general')).status_code==200
    invoice=upload(client,login,w['id']);link=request(client,login,'empresa-a','post',f"/documents/{invoice['id']}/link")['url']
    request(client,login,'admin','patch',f"/admin/companies/{w['company_id']}",{'status':'suspendida'})
    assert client.get(f"/api/documents/{invoice['id']}/download",headers=login('empresa-a')).status_code==403
    assert client.get(link).status_code==403

def test_valid_import_confirmation_and_failed_rollback(client,login,app):
    w=work(client,login,'DEMO-PROYECTO');book=openpyxl.Workbook();sheet=book.active
    sheet.append(['codigo','descripcion','unidad','cantidad','precio_unitario']);sheet.append(['9','Rubro importado','m2',10,100]);content=BytesIO();book.save(content)
    response=client.post(f"/api/works/{w['id']}/imports/preview",headers=login('tecnico'),data={'file':(BytesIO(content.getvalue()),'rubrado.xlsx'),'kind':'rubrado'});assert response.status_code==201
    batch=response.json['import'];payload={'confirm':True,'sha256':batch['sha256'],'contract':{'kind':'inicial','rules':{'iva_rate':'0.22','social_payment':'separado'}}}
    with app.app_context():before=Contract.query.count()
    assert client.post(f"/api/imports/{batch['id']}/confirm",headers=login('tecnico'),json={**payload,'contract':{'rules':{'iva_rate':'9'}}}).status_code==422
    with app.app_context():assert Contract.query.count()==before
    assert client.post(f"/api/imports/{batch['id']}/confirm",headers=login('tecnico'),json=payload).status_code==200
    assert client.post(f"/api/imports/{batch['id']}/confirm",headers=login('tecnico'),json=payload).status_code==409

def test_receipt_requirements_incidence_extension(client,login):
    w=work(client,login,'DEMO-MOLINO');end=w['end_date']
    r=request(client,login,'inspector','post',f"/works/{w['id']}/records",{'kind':'incidencia','title':'Lluvia registrada','data':{'type':'lluvia','description':'Lluvia sintética, no prórroga automática'}},201)
    assert work(client,login,'DEMO-MOLINO')['end_date']==end
    assert client.post(f"/api/works/{w['id']}/records",headers=login('director'),json={'kind':'recepcion','title':'No corresponde','data':{'type':'definitiva'}}).status_code==409
    from datetime import date,timedelta
    new_end=(date.fromisoformat(end)+timedelta(days=10)).isoformat()
    extension=request(client,login,'director','post',f"/works/{w['id']}/records",{'kind':'prorroga','title':'Extensión justificada','data':{'new_end_date':new_end}},201)['record']
    request(client,login,'general','post',f"/works/{w['id']}/records/{extension['id']}/transition",{'version':extension['version'],'status':'aprobado','comment':'Autorización expresa demo'})
    assert work(client,login,'DEMO-MOLINO')['end_date']==new_end

def test_provider_error_core_still_works(client,login,monkeypatch):
    w=work(client,login,'DEMO-MOLINO');d=upload(client,login,w['id'],'admin','mantenimiento.txt','informe',b'Las canaletas se revisan mensualmente.')
    request(client,login,'admin','post',f"/documents/{d['id']}/ingest")
    from app.ai import provider
    def fail(*args):raise provider.ProviderUnavailable('Timeout simulado de test','provider_timeout')
    monkeypatch.setattr(provider,'answer_stream',fail)
    response=client.post(f"/api/works/{w['id']}/chat",headers=login('empresa-a'),json={'query':'canaletas'})
    assert b'event: error' in response.data and b'provider_timeout' in response.data
    assert client.get('/api/works',headers=login('empresa-a')).status_code==200

def test_missing_external_workbook_is_blocked_without_private_originals():
    from zipfile import ZipFile, ZIP_DEFLATED
    book=openpyxl.Workbook();sheet=book.active
    sheet.append(['codigo','descripcion','unidad','cantidad','precio_unitario'])
    sheet.append(['A','Rubro sintético','m2',10,"='[1]Adicional-demo'!A1"])
    original=BytesIO();book.save(original);content=BytesIO()
    with ZipFile(original) as source,ZipFile(content,'w',ZIP_DEFLATED) as target:
        for name in source.namelist():target.writestr(name,source.read(name))
        target.writestr('xl/externalLinks/_rels/externalLink1.xml.rels',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" '
            'Target="adicional-demo-ausente.xlsx" TargetMode="External"/></Relationships>')
    result=preview(content.getvalue(),'demo-con-fuente-ausente.xlsx','rubrado')
    assert any('adicional-demo-ausente.xlsx' in error and 'ausente' in error.lower() for error in result['errors'])
    assert any('Referencia externa' in error for error in result['errors'])
    assert not result['rows']


def test_empty_business_database_only_identities(client,login,app):
    from sqlalchemy import text
    with app.app_context():
        assert db.engine.url.database=='obras_test'
        db.session.execute(text('SET FOREIGN_KEY_CHECKS=0'))
        for table in reversed(db.metadata.sorted_tables):db.session.execute(table.delete())
        db.session.execute(text('SET FOREIGN_KEY_CHECKS=1'));db.session.commit();seed(accounts_only=True)
        assert Intervention.query.count()==0 and Certificate.query.count()==0
    assert request(client,login,'tecnico','get','/works')['total']==0
    w=request(client,login,'tecnico','post','/works',{'name':'Base vacía funcional','description':'Sin ID del seed de obras','locality':'Minas'},201)['work']
    assert request(client,login,'tecnico','get',f"/works/{w['id']}")['actors'][0]['user_id']


def test_definitive_receipt_after_requirements_and_alert_clear(client,login):
    from datetime import date,timedelta
    w=work(client,login,'DEMO-POSOBRA');work_id=w['id']
    for observation in request(client,login,'director','get',f'/works/{work_id}/records?kind=observacion')['records']:
        r=request(client,login,'empresa-a','post',f"/works/{work_id}/records/{observation['id']}/transition",{'version':observation['version'],'status':'respuesta','comment':'Corrección de prueba'})['record']
        request(client,login,'director','post',f"/works/{work_id}/records/{r['id']}/transition",{'version':r['version'],'status':'cerrado','comment':'Verificada y cerrada'})
    act=upload(client,login,work_id,'director',kind='acta_recepcion')
    upload(client,login,work_id,'director',kind='manual_mantenimiento')
    yesterday=(date.today()-timedelta(days=1)).isoformat()
    request(client,login,'director','post',f'/works/{work_id}/records',{'kind':'recepcion','title':'Provisoria cumplida','date':yesterday,'data':{'type':'provisoria','definitive_date':yesterday,'document_ids':[act['id']]}},201)
    request(client,login,'director','post',f'/works/{work_id}/records',{'kind':'recepcion','title':'Definitiva prueba','date':date.today().isoformat(),'data':{'type':'definitiva','document_ids':[act['id']]}},201)
    rows=request(client,login,'director','get',f'/works/{work_id}/records?kind=recepcion')['records']
    assert next(r for r in rows if r['data']['type']=='provisoria')['status']=='cumplida'
