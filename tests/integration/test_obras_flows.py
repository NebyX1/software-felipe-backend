import json
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from app.extensions import db
from app.models.domain import Intervention,Document,Certificate,Rectification
from app.models import User
from app.services.reports import pdf_report

def request(client,login,role,method,path,data=None,status=200):
    r=getattr(client,method)('/api'+path,headers=login(role),json=data)
    assert r.status_code==status,(path,r.status_code,r.json)
    return r.json

def works(client,login,role='admin'):
    return request(client,login,role,'get','/works')['works']

def work(client,login,code):return next(w for w in works(client,login) if w['code']==code)

def upload(client,login,work_id,role='empresa-a',name='factura-demo.pdf',kind='factura',content=None,**extra):
    if content is None:content=pdf_report('Factura FICTICIA',['Prueba sintética, sin validez institucional.'])
    response=client.post(f'/api/works/{work_id}/documents',headers=login(role),data={'file':(BytesIO(content),name),'kind':kind,'classification':'reservado',**extra})
    assert response.status_code==201,response.json
    return response.json['document']

def cert_new(client,login,w,period='2026-01',amount='20',key=None):
    return request(client,login,'empresa-a','post',f"/works/{w['id']}/certificates",{'period':period,'mode':'periodo','advances':{'1.1':amount,'2.1':amount},'icc_current':'115.52','idempotency_key':key or str(uuid4())},201)['certificate']

def step(client,login,w,c,role,status,**extra):
    return request(client,login,role,'post',f"/works/{w['id']}/certificates/{c['id']}/transition",{'version':c['version'],'status':status,**extra})['certificate']

def approve(client,login,w,c):
    c=step(client,login,w,c,'empresa-a','presentado');c=step(client,login,w,c,'director','aprobacion_inicial')
    invoice=upload(client,login,w['id'])
    c=step(client,login,w,c,'empresa-a','facturado',invoice_id=invoice['id'],invoice_number='DEMO-F-01')
    return step(client,login,w,c,'general','aprobado')

def test_dummy_session_logout_and_server_role(client,login,app):
    assert len(client.get('/api/auth/accounts').json['accounts'])==9
    assert client.post('/api/auth/login',json={'account':'inventada','role':'super_admin'}).status_code==401
    assert client.get('/api/works').status_code==401
    h=login('empresa-a');assert client.get('/api/auth/me',headers=h).json['user']['role']=='empresa'
    assert client.post('/api/works',headers=h,json={'name':'Hack','role':'super_admin'}).status_code==403
    assert client.post('/api/auth/logout',headers=h).status_code==200
    assert client.get('/api/auth/me',headers=h).status_code==401
    technical_headers=login('tecnico')
    app.config['DEMO_AUTH_ENABLED']=False
    assert client.get('/api/auth/accounts').status_code==404
    assert client.get('/api/works',headers=technical_headers).status_code==401
    app.config['DEMO_AUTH_ENABLED']=True

def test_company_isolation_documents_exports_and_search(client,login):
    a=work(client,login,'DEMO-MOLINO');b=work(client,login,'DEMO-BULEVAR')
    assert all(w['company_id']==a['company_id'] for w in works(client,login,'empresa-a'))
    assert client.get(f"/api/works/{b['id']}",headers=login('empresa-a')).status_code==404
    doc=upload(client,login,b['id'],'empresa-b',name='informe.txt',kind='informe',content=b'Empresa B, canaletas secretas del Bulevar')
    for path in [f"/documents/{doc['id']}/download",f"/documents/{doc['id']}/annotations",f"/works/{b['id']}/search?q=canaletas",f"/works/{b['id']}/dossier.zip"]:
        assert client.get('/api'+path,headers=login('empresa-a')).status_code==404
    assert client.post(f"/api/documents/{doc['id']}/ingest",headers=login('empresa-a')).status_code==404
    report=client.get('/api/reports/works.csv',headers=login('empresa-a'))
    assert b['name'].encode() not in report.data
    public=client.get('/api/public/works').json['works'];assert all('company_id' not in w and 'description' not in w for w in public)

def test_full_certificate_revision_invoice_pdf_payment(client,login,app):
    w=work(client,login,'DEMO-MOLINO');c=cert_new(client,login,w)
    assert client.post(f"/api/works/{w['id']}/certificates/{c['id']}/transition",headers=login('general'),json={'version':c['version'],'status':'aprobado'}).status_code==409
    c=step(client,login,w,c,'empresa-a','presentado')
    c=step(client,login,w,c,'director','observado',comment='Revisar medición')
    c=request(client,login,'empresa-a','patch',f"/works/{w['id']}/certificates/{c['id']}",{'version':c['version'],'advances':{'1.1':'25','2.1':'25'},'icc_current':'115.52'})['certificate']
    c=approve(client,login,w,c)
    assert c['certificate_document_id'] and c['payment_document_id']
    assert len(request(client,login,'empresa-a','get',f"/works/{w['id']}/certificates/{c['id']}/revisions")['revisions'])==2
    pdf=client.get(f"/api/documents/{c['certificate_document_id']}/download",headers=login('empresa-a'));assert pdf.data.startswith(b'%PDF')
    from pypdf import PdfReader
    assert 'DEMO' in PdfReader(BytesIO(pdf.data)).pages[0].extract_text()
    assert client.delete(f"/api/documents/{c['invoice_id']}",headers=login('empresa-a')).status_code==409
    assert work(client,login,'DEMO-MOLINO')['metrics']['physical_percent']=='25.00'
    p=request(client,login,'administrativo','get',f"/works/{w['id']}/payments")['payments'][0]
    proof=upload(client,login,w['id'],'admin',kind='resolucion')
    for target in ['hacienda','secretaria_general','resolucion','contaduria_tesoreria','pagado']:
        p=request(client,login,'general' if target=='resolucion' else 'administrativo','post',f"/works/{w['id']}/payments/{p['id']}/transition",{'version':p['version'],'status':target,'comment':'Actuación sintética','budget_available':True,'confirm_demo':True,'document_ids':[proof['id']]})['payment']
    assert p['confirmation']['fictitious'] and work(client,login,'DEMO-MOLINO')['metrics']['paid']==c['calculation']['payable']

def test_idempotency_invalid_previous_and_concurrency(client,login,app):
    w=work(client,login,'DEMO-MOLINO');key=str(uuid4());c=cert_new(client,login,w,key=key)
    payload={'period':'2026-01','mode':'periodo','advances':{'1.1':'20','2.1':'20'},'icc_current':'115.52','idempotency_key':key}
    assert request(client,login,'empresa-a','post',f"/works/{w['id']}/certificates",payload)['certificate']['id']==c['id']
    assert client.post(f"/api/works/{w['id']}/certificates",headers=login('empresa-a'),json={**payload,'start_date':'2026-01-02'}).status_code==409
    assert client.post(f"/api/works/{w['id']}/certificates",headers=login('empresa-a'),json={**payload,'period':'0000-01'}).status_code==422
    assert client.post(f"/api/works/{w['id']}/certificates",headers=login('empresa-a'),json={**payload,'idempotency_key':str(uuid4())}).status_code==409
    c=approve(client,login,w,c);headers=login('empresa-a')
    def send():
        with app.test_client() as other:return other.post(f"/api/works/{w['id']}/certificates",headers=headers,json={**payload,'period':'2026-02','idempotency_key':str(uuid4())}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(lambda _:send(),range(2)))==[201,409]

def test_rectification_immutable_and_negative_delta(client,login,app):
    w=work(client,login,'DEMO-MOLINO');c=approve(client,login,w,cert_new(client,login,w));snapshot=c['approved_snapshot']
    r=request(client,login,'director','post',f"/works/{w['id']}/certificates/{c['id']}/rectifications",{'reason':'Medición corregida','mode':'periodo','advances':{'1.1':'10','2.1':'10'},'icc_current':'115.52'},201)['rectification']
    assert float(r['snapshot']['delta'])<0
    resolved=request(client,login,'general','post',f"/works/{w['id']}/certificates/{c['id']}/rectifications/{r['id']}/resolve",{'version':r['version'],'status':'aprobada'})['rectification']
    pdf=client.get(f"/api/documents/{resolved['snapshot']['document_id']}/download",headers=login('empresa-a'))
    assert pdf.status_code==200 and pdf.data.startswith(b'%PDF')
    assert work(client,login,'DEMO-MOLINO')['metrics']['physical_percent']=='10.00'
    with app.app_context():assert db.session.get(Certificate,c['id']).approved_snapshot==snapshot

def test_document_versions_notes_signed_links_and_rag(client,login,monkeypatch):
    w=work(client,login,'DEMO-MOLINO');d=upload(client,login,w['id'],'admin','manual.txt','informe',b'Las canaletas deben revisarse trimestralmente.')
    request(client,login,'director','post',f"/documents/{d['id']}/annotations",{'page':1,'x':'0.5','y':'0.4','text':'Revisar detalle'},201)
    request(client,login,'admin','post',f"/documents/{d['id']}/ingest")
    sources=request(client,login,'empresa-a','get',f"/works/{w['id']}/search?q=canaletas")['sources'];assert sources and sources[0]['version']==1
    from app.ai import provider
    def mock(query,sources):
        yield 'token',{'text':'Revisar trimestralmente.'}
        yield 'done',{'message':'Revisar trimestralmente.','citations':[sources[0]['id']]}
    monkeypatch.setattr(provider,'answer_stream',mock)
    r=client.post(f"/api/works/{w['id']}/chat",headers=login('empresa-a'),json={'query':'canaletas'});assert b'event: token' in r.data and b'event: done' in r.data
    assert request(client,login,'empresa-a','get',f"/works/{w['id']}/chat")['turns'][0]['query']=='canaletas'
    link=request(client,login,'empresa-a','post',f"/documents/{d['id']}/link")['url'];assert client.get(link).status_code==200
    request(client,login,'empresa-a','post','/auth/logout');assert client.get(link).status_code==403
    new=upload(client,login,w['id'],'admin','manual.txt','informe',b'Las canaletas se revisan mensualmente.',previous_id=str(d['id']))
    assert new['version']==2
    assert request(client,login,'admin','get',f"/works/{w['id']}/search?q=canaletas")['sources']==[]
    assert request(client,login,'director','get',f"/documents/{d['id']}/annotations")['annotations'][0]['text']=='Revisar detalle'

def test_new_work_from_empty_preparation_execution_posobra(client,login):
    users=request(client,login,'admin','get','/reference')['users'];director=next(u for u in users if u['role']=='director_obra')
    w=request(client,login,'tecnico','post','/works',{'name':'Intervención creada desde cero','description':'Objeto sintético','locality':'Minas','latitude':'-34.37','longitude':'-55.24'},201)['work']
    request(client,login,'admin','post',f"/works/{w['id']}/actors",{'user_id':director['id'],'role':'Dirección'},201)
    company=work(client,login,'DEMO-MOLINO')['company_id']
    contract=request(client,login,'director','post',f"/works/{w['id']}/contracts",{'kind':'contractual','company_id':company,'number':'DEMO-NUEVO','start_date':'2026-01-01','end_date':'2026-12-31','rules':{'iva_rate':'0.22','social_payment':'separado'},'lines':[{'code':'1.1','description':'Prueba','unit':'m2','quantity':'10','unit_price':'200'}]},201)['contract']
    request(client,login,'director','post',f"/works/{w['id']}/contracts/{contract['id']}/approve")
    s=request(client,login,'director','post',f"/works/{w['id']}/schedules",{'kind':'contractual','activities':[{'title':'Obra','start':'2026-01-01','end':'2026-12-31','responsible_id':director['id']}]},201)['schedule']
    request(client,login,'director','post',f"/works/{w['id']}/schedules/{s['id']}/approve")
    w=request(client,login,'director','post',f"/works/{w['id']}/transition",{'version':w['version'],'stage':'obra'})['work']
    c=request(client,login,'empresa-a','post',f"/works/{w['id']}/certificates",{'period':'2026-01','mode':'periodo','advances':{'1.1':'100'},'idempotency_key':str(uuid4())},201)['certificate'];approve(client,login,w,c)
    upload(client,login,w['id'],'director',kind='plano_final')
    w=request(client,login,'director','post',f"/works/{w['id']}/transition",{'version':w['version'],'stage':'posobra'})['work']
    doc=upload(client,login,w['id'],'director',kind='acta_recepcion')
    m=request(client,login,'director','post',f"/works/{w['id']}/records",{'kind':'mantenimiento','title':'Revisar canaletas','due_date':'2026-10-15','responsible_id':director['id'],'data':{'frequency':'trimestral'}},201)['record']
    m=request(client,login,'director','post',f"/works/{w['id']}/records/{m['id']}/transition",{'version':m['version'],'status':'realizado','comment':'Realizado con evidencia','document_ids':[doc['id']]})['record']
    request(client,login,'general','post',f"/works/{w['id']}/records/{m['id']}/transition",{'version':m['version'],'status':'revisado','comment':'Revisión aprobada'})
    assert len(request(client,login,'director','get',f"/works/{w['id']}/records?kind=mantenimiento")['records'])==2
