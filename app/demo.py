"""Idempotent, synthetic seeds. No institutional users, approvals or payments."""
from datetime import date,timedelta
from io import BytesIO
from uuid import uuid4
import click
from flask import current_app,g
from flask.cli import with_appcontext
from PIL import Image,ImageDraw
from .extensions import db
from .models import User,Unit
from .models.domain import Company,Professional,Intervention,Assignment,Contract,BudgetLine,Schedule,Record,Document,Certificate,CertificateRevision,Rectification,Payment,CatalogEntry,Chunk,History,ChatTurn,ImportBatch,Annotation
from .models.domain import CompanyRepresentative, CompanyDocument, PaymentAttempt, Procedure, Notification, DemoPaymentRun, CheckoutSession
from .services.errors import require
from .services.economics import calculate
from .services.reports import pdf_report
from .services.documents import store_document
from .infrastructure.storage import get_document_storage

ACCOUNTS=[('admin','Administrador Demo','super_admin'),('general','Dirección General Demo','direccion_general'),('director','Dirección de Obra Demo','director_obra'),('tecnico','Técnica de Proyecto Demo','tecnico'),('inspector','Inspector Demo','inspector'),('administrativo','Administrativo Demo','administrativo'),('consulta','Consulta Ejecutiva Demo','consulta'),('empresa-a','Representante Empresa Demo A','empresa'),('empresa-b','Representante Empresa Demo B','empresa')]


def seed(with_certificates=True,accounts_only=False):
    require(current_app.config['DEMO_AUTH_ENABLED'] and current_app.config['DEMO_ENVIRONMENT'],'Seed sólo permitido en entorno demo explícito.')
    unit=Unit.query.filter_by(name='Dirección de Obras · Demo').first()
    if not unit:
        unit=Unit(name='Dirección de Obras · Demo',color='#196b83',emoji='')
        db.session.add(unit)
        db.session.flush()
    companies=[]
    for letter in ('A','B'):
        company=Company.query.filter_by(rut='DEMO-'+letter).first()
        if not company:
            company=Company(name='Empresa Demo '+letter,rut='DEMO-'+letter,demo=True,status='activa',contact={'email':'empresa-'+letter.lower()+'@demo.invalid','notice':'Datos ficticios'})
            db.session.add(company)
            db.session.flush()
        companies.append(company)
    users={}
    for key,name,role in ACCOUNTS:
        user=User.query.filter_by(email=key+'@demo.invalid').first()
        if not user:
            user=User(name=name,email=key+'@demo.invalid',role=role,unit_id=unit.id,demo=True,company_id=companies[0].id if key=='empresa-a' else companies[1].id if key=='empresa-b' else None)
            user.set_password('DemoObras2026!')
            db.session.add(user)
            db.session.flush()
        users[key]=user
        if role == 'empresa' and not CompanyRepresentative.query.filter_by(user_id=user.id).first():
            db.session.add(CompanyRepresentative(company_id=user.company_id, user_id=user.id, status='validada',
                                                start_date=date.today()-timedelta(days=1), end_date=date.today()+timedelta(days=365),
                                                validated_by=users['admin'].id))
    for kind,code,label in [('objetivo','patrimonio','Recuperación del patrimonio'),('objetivo','movilidad','Movilidad y accesibilidad'),('tipo','edificacion','Edificación'),('tipo','vialidad','Infraestructura vial'),('financiacion','demo','Financiación de demostración')]:
        if not CatalogEntry.query.filter_by(kind=kind,code=code).first():
            db.session.add(CatalogEntry(kind=kind,code=code,label=label,data={}))
    if not Professional.query.filter_by(registration='PROF-DEMO-01').first():
        db.session.add(Professional(name='Profesional de Proyecto Demo',registration='PROF-DEMO-01',contact={'email':'proyecto@demo.invalid'},source='Sintético, sin datos del registro original'))
    g.user=users['admin']
    for company in companies:
        name = f'representacion-sintetica-{company.rut}.pdf'
        evidence = CompanyDocument.query.filter_by(company_id=company.id, name=name).first()
        if not evidence:
            binary = pdf_report('Constancia de representación SINTÉTICA', [
                f'Empresa: {company.name} · {company.rut}', 'Identidad y representación creadas únicamente para demostración.',
                'No acredita poder, registro público ni representación institucional.'])
            key, digest = get_document_storage().put(binary)
            evidence = CompanyDocument(company_id=company.id, name=name, kind='representacion', author_id=g.user.id,
                                       storage_key=key, sha256=digest, mime='application/pdf', size=len(binary), status='validado')
            db.session.add(evidence)
            db.session.flush()
        for representative in CompanyRepresentative.query.filter_by(company_id=company.id):
            if representative.evidence_id is None and db.session.get(User, representative.user_id).demo:
                representative.evidence_id = evidence.id
    if accounts_only:
        db.session.commit();return users
    scenarios=[('DEMO-PROYECTO','Centro Comunitario · Proyecto Demo','proyecto',None,-34.370,-55.235),('DEMO-MOLINO','Molino · Ejecución Demo','obra',companies[0],-34.377,-55.236),('DEMO-BULEVAR','Bulevar Artigas · Obra Demo','obra',companies[1],-34.380,-55.242),('DEMO-POSOBRA','Espacio Público · Posobra Demo','posobra',companies[0],-34.366,-55.230),('DEMO-PAGO','Transferencia electrónica · Demo Tesorería','obra',companies[0],-34.373,-55.239)]
    for code,name,stage,company,lat,lon in scenarios:
        if Intervention.query.filter_by(code=code).first():
            continue
        work=Intervention(code=code,name=name,locality='Minas',description='Escenario sintético. Las referencias Molino/Bulevar orientan el modelo; responsables, aprobaciones y pagos son ficticios.',stage=stage,status='en_ejecucion' if stage=='obra' else 'finalizada' if stage=='posobra' else 'en_preparacion',latitude=lat,longitude=lon,surface=250,budget=1200000,objective='Recuperación del patrimonio' if 'MOLINO' in code else 'Movilidad y accesibilidad',company_id=company.id if company else None,unit_id=unit.id,created_by=users['tecnico'].id,start_date=date.today()-timedelta(days=60),end_date=date.today()+timedelta(days=120),funding=[{'name':'Demo','amount':'1200000.00'}],public=code!='DEMO-BULEVAR',demo=True)
        db.session.add(work)
        db.session.flush()
        for key in ('director','tecnico','inspector'):
            db.session.add(Assignment(work_id=work.id,user_id=users[key].id,role=users[key].role,contact={'email':users[key].email}))
        rules={'iva_rate':'0.22','social_payment':'separado','notice':'Reglas contractuales de demostración, no tasa universal'}
        if 'MOLINO' in code:
            rules['icc_initial']='107.46363516'
        contract=Contract(work_id=work.id,version=1,kind='inicial' if stage=='proyecto' else 'contractual',status='aprobado',company_id=company.id if company else None,number='DEMO-CON-'+str(work.id),tender_number='DEMO-LIC-'+str(work.id),dossier_number='DEMO-EXP-'+str(work.id),bps_number='BPS-DEMO',start_date=work.start_date,end_date=work.end_date,amount='1220000',rules=rules)
        db.session.add(contract)
        db.session.flush()
        lines=[BudgetLine(contract_id=contract.id,code='1.1',chapter='Preparación',description='Implantación y preparación del sitio',unit='global',quantity=1,unit_price=100000,social_rate='0.121' if 'BULEVAR' in code else 0),BudgetLine(contract_id=contract.id,code='2.1',chapter='Construcción',description='Intervención principal de demostración',unit='m2',quantity=100,unit_price=9000,social_rate='0.121' if 'BULEVAR' in code else 0)]
        db.session.add_all(lines)
        db.session.flush()
        db.session.add(Schedule(work_id=work.id,version=1,kind=contract.kind,status='aprobado',activities=[{'title':'Preparación','start':work.start_date.isoformat(),'end':(work.start_date+timedelta(days=30)).isoformat(),'responsible_id':users['director'].id,'code':'1.1'},{'title':'Ejecución','start':(work.start_date+timedelta(days=31)).isoformat(),'end':work.end_date.isoformat(),'responsible_id':users['tecnico'].id,'code':'2.1'}],reason='Baseline de demostración'))
        db.session.add(Record(work_id=work.id,kind='tarea',title='Revisar documentación de la intervención',status='pendiente',responsible_id=users['tecnico'].id,due_date=date.today()+timedelta(days=3),date=date.today(),author_id=users['director'].id,data={'description':'Revisión técnica de demostración','priority':'alta','comments':[]}))
        pdf=pdf_report('Plano e informe sintético de demostración',[f'Intervención: {work.name}','El mantenimiento debe revisar canaletas cada trimestre.','Las observaciones se responden por escrito y se cierran luego de revisión técnica.','Documento sin validez institucional.'])
        store_document(work,pdf,'plano-demo.pdf',{'kind':'plano_final' if stage=='posobra' else 'plano','classification':'reservado' if company else 'interno'})
        image=Image.new('RGB',(1200,600),'#dce6dc')
        draw=ImageDraw.Draw(image)
        draw.rectangle((120,180,1070,540),fill='#d1c4a1',outline='#436573',width=8)
        draw.polygon([(80,180),(600,60),(1120,180)],fill='#436573')
        draw.text((35,30),'DOCUMENTO FOTOGRAFICO SINTETICO - DEMO',fill='#183a56')
        imagefile=BytesIO()
        image.save(imagefile,'PNG')
        store_document(work,imagefile.getvalue(),'portada-demo.png',{'kind':'portada','classification':'publico'})
        if company:
            store_document(work,pdf,'acta-inicio-demo.pdf',{'kind':'acta_inicio','classification':'reservado'})
            db.session.add(Record(work_id=work.id,kind='observacion',title='Revisar terminación de encuentro',status='observado',responsible_id=users['director'].id,due_date=date.today()+timedelta(days=5),date=date.today(),author_id=users['inspector'].id,data={'description':'Observación sintética para intercambio con la empresa','comments':[]}))
        if stage=='posobra':
            for days,title in [(-3,'Revisión trimestral de canaletas'),(7,'Inspección estacional de pintura')]:
                db.session.add(Record(work_id=work.id,kind='mantenimiento',title=title,status='pendiente',responsible_id=users['director'].id,due_date=date.today()+timedelta(days=days),date=date.today(),author_id=users['general'].id,data={'frequency':'trimestral','description':'Plan de mantenimiento sintético','comments':[]}))
    db.session.commit()
    if with_certificates:
        seed_circuits(users)
    return users


def seed_circuits(users):
    from .services.certification import new_certificate,transition
    from .services.works import save_record
    from .services.reports import certificate_pdfs
    today=date.today();absolute=today.year*12+today.month-1
    old=f'{(absolute-2)//12:04d}-{(absolute-2)%12+1:02d}'
    recent=f'{(absolute-1)//12:04d}-{(absolute-1)%12+1:02d}'
    for code,company,period,advance,final in [('DEMO-MOLINO','empresa-a',old,'10',True),('DEMO-MOLINO','empresa-a',recent,'15',False),('DEMO-BULEVAR','empresa-b',recent,'20',False),('DEMO-POSOBRA','empresa-a',old,'100',True),('DEMO-PAGO','empresa-a',recent,'25',True)]:
        work=Intervention.query.filter_by(code=code).first()
        if Certificate.query.filter_by(work_id=work.id,period=period).first():continue
        saved_stage=work.stage;work.stage='obra';g.user=users[company]
        cert,_=new_certificate(work,{'period':period,'mode':'periodo','advances':{'1.1':advance,'2.1':advance},'icc_current':'115.52' if code=='DEMO-MOLINO' else None,'idempotency_key':'seed-'+code+'-'+period})
        if code!='DEMO-BULEVAR':
            transition(cert,{'version':cert.version,'status':'presentado'})
            g.user=users['director']
            transition(cert,{'version':cert.version,'status':'aprobacion_inicial' if final else 'observado','comment':'Observación sintética: verificar medición del rubro 2.1'})
            if final:
                g.user=users[company]
                invoice=store_document(work,pdf_report('Factura ficticia DEMO',[work.name,'Documento sintético sin validez fiscal']),f'factura-demo-{period}.pdf',{'kind':'factura','classification':'reservado'})
                transition(cert,{'version':cert.version,'status':'facturado','invoice_id':invoice.id,'invoice_number':'DEMO-F-'+period})
                g.user=users['general'];transition(cert,{'version':cert.version,'status':'aprobado'})
        work.stage=saved_stage;db.session.commit()
        if final:certificate_pdfs(cert,work)
        if code == 'DEMO-PAGO':
            from .services.certification import payment_transition
            payment = Payment.query.filter_by(certificate_id=cert.id).first()
            g.user = users['general']
            resolution = store_document(work, pdf_report('Resolución de pago FICTICIA', ['Autorización sintética para probar el simulador interno de transferencias.']),
                                        'resolucion-transferencia-demo.pdf', {'kind': 'resolucion', 'classification': 'reservado'})
            for step in ('hacienda', 'secretaria_general', 'resolucion', 'contaduria_tesoreria'):
                payment_transition(work, payment, {'version': payment.version, 'status': step, 'comment': 'Actuación sintética para la presentación',
                                                  'budget_available': True, 'document_ids': [resolution.id]})
            db.session.commit()
    g.user=users['admin'];work=Intervention.query.filter_by(code='DEMO-POSOBRA').first()
    if not Record.query.filter_by(work_id=work.id,kind='recepcion').first():
        manual=store_document(work,pdf_report('Manual de mantenimiento DEMO',['Canaletas: revisión trimestral. Pintura: inspección estacional.']), 'manual-mantenimiento-demo.pdf',{'kind':'manual_mantenimiento','classification':'reservado'})
        act=store_document(work,pdf_report('Acta de recepción provisoria DEMO',['Recepción sintética, sujeta a revisión de observaciones.']), 'recepcion-provisoria-demo.pdf',{'kind':'acta_recepcion','classification':'reservado'})
        save_record(work,{'kind':'recepcion','title':'Recepción provisoria de demostración','date':(today-timedelta(days=90)).isoformat(),'data':{'type':'provisoria','definitive_date':(today+timedelta(days=7)).isoformat(),'document_ids':[act.id]}})
    db.session.commit()


@click.command('seed-demo')
@click.option('--accounts-only',is_flag=True,help='Crear identidades/catálogos sintéticos sin intervenciones.')
@with_appcontext
def seed_demo(accounts_only):
    seed(accounts_only=accounts_only)
    click.echo('Demo sembrada de forma idempotente; cuentas en docs/DEMO_GUIDE.md. Todo dato añadido es sintético.')


@click.command('reset-demo')
@click.option('--confirm-database',required=True)
@with_appcontext
def reset_demo(confirm_database):
    name=db.engine.url.database
    require(current_app.config['DEMO_ENVIRONMENT'] and current_app.config['DEMO_AUTH_ENABLED'] and name in ('obras_demo','obras_test') and confirm_database==name,'Reset permitido sólo en esquema demo/test confirmado.')
    ids=[w.id for w in Intervention.query.filter_by(demo=True)]
    certids=[c.id for c in Certificate.query.filter(Certificate.work_id.in_(ids))]
    docids=[d.id for d in Document.query.filter(Document.work_id.in_(ids))]
    for model,criterion in [(DemoPaymentRun,DemoPaymentRun.work_id.in_(ids)),(CheckoutSession,CheckoutSession.payment_id.in_(db.select(Payment.id).where(Payment.certificate_id.in_(certids)))),(PaymentAttempt,PaymentAttempt.payment_id.in_(db.select(Payment.id).where(Payment.certificate_id.in_(certids)))),(Procedure,Procedure.work_id.in_(ids)),(Notification,Notification.work_id.in_(ids)),(Rectification,Rectification.certificate_id.in_(certids)),(Payment,Payment.certificate_id.in_(certids)),(CertificateRevision,CertificateRevision.certificate_id.in_(certids)),(Chunk,Chunk.document_id.in_(docids)),(Annotation,Annotation.document_id.in_(docids)),(ChatTurn,ChatTurn.work_id.in_(ids)),(ImportBatch,ImportBatch.work_id.in_(ids)),(History,History.work_id.in_(ids))]:
        model.query.filter(criterion).delete(synchronize_session=False)
    Certificate.query.filter(Certificate.work_id.in_(ids)).delete(synchronize_session=False)
    Document.query.filter(Document.work_id.in_(ids)).delete(synchronize_session=False)
    for model in (Assignment,Schedule,Record,Contract):
        if model==Contract:
            BudgetLine.query.filter(BudgetLine.contract_id.in_(db.select(Contract.id).where(Contract.work_id.in_(ids)))).delete(synchronize_session=False)
        model.query.filter(model.work_id.in_(ids)).delete(synchronize_session=False)
    Intervention.query.filter(Intervention.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    seed()
    click.echo('Sólo intervenciones demo reiniciadas. Usuarios, empresas y obras ajenas al seed conservadas; objetos originales retenidos.')


@click.command('init-bucket')
@with_appcontext
def init_bucket():
    storage=get_document_storage()
    require(storage.kind=='private-minio','Inicialización sólo para MinIO.')
    if not storage.client.bucket_exists(storage.bucket):
        storage.client.make_bucket(storage.bucket)
    from minio.versioningconfig import VersioningConfig,ENABLED
    storage.client.set_bucket_versioning(storage.bucket,VersioningConfig(ENABLED))
    click.echo('Bucket privado verificado; versionado habilitado.')
