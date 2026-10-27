"""Corrections append snapshots, never overwrite final certificates."""
import copy
from flask import g
from ..extensions import db
from ..models.domain import Certificate,Rectification,Payment
from .access import roles,history,check_version
from .economics import calculate,decimal,money
from .errors import require
from .works import text

def effective_snapshot(certificate):
    correction=Rectification.query.filter_by(certificate_id=certificate.id,status='aprobada').order_by(Rectification.id.desc()).first()
    return correction.snapshot['after'] if correction else certificate.approved_snapshot

def eligible(cert):
    require(cert.status=='aprobado','Sólo se rectifican certificados definitivos.',409)
    require(not Certificate.query.filter(Certificate.work_id==cert.work_id,Certificate.period>cert.period).count(),'Rectificá antes de abrir períodos posteriores; conserva la cadena acumulada.',409)
    payment=Payment.query.filter_by(certificate_id=cert.id).with_for_update().first()
    require(payment and payment.status=='expediente','La rectificación se resuelve antes del pase a Hacienda.',409)
    return payment

def request_correction(cert,payload):
    roles('director_obra','direccion_general','super_admin','admin');eligible(cert)
    require(not Rectification.query.filter_by(certificate_id=cert.id,status='solicitada').count(),'Hay una rectificación pendiente.',409)
    before=effective_snapshot(cert)
    previous={l['code']:l['previous'] for l in before['calculation']['lines']}
    quantities={l['code']:l['previous_quantity'] for l in before['calculation']['lines'] if 'previous_quantity' in l}
    calculation=calculate(before['calculation']['lines'],payload.get('advances',{}),previous,before['contract']['rules'],payload.get('mode','periodo'),payload.get('icc_current'),quantities)
    after=copy.deepcopy(before);after['calculation']=calculation
    correction=Rectification(certificate_id=cert.id,reason=text(payload.get('reason',''),'Motivo de rectificación'),requested_by=g.user.id,snapshot={'before':before,'after':after,'delta':str(money(decimal(calculation['payable'])-decimal(before['calculation']['payable']))),'mode':payload.get('mode','periodo'),'input':payload.get('advances',{})})
    db.session.add(correction);db.session.flush()
    history(cert.work_id,'certificado',cert.id,'solicitar_rectificacion',details={'rectification_id':correction.id,'delta':correction.snapshot['delta'],'reason':correction.reason})
    return correction

def resolve(cert,correction,payload):
    roles('direccion_general','super_admin','admin');payment=eligible(cert);check_version(correction,payload)
    require(correction.status=='solicitada' and payload.get('status') in ('aprobada','rechazada'),'Rectificación ya resuelta o estado inválido.',409)
    if payload['status']=='aprobada':
        require(effective_snapshot(cert)==correction.snapshot['before'],'Cambió la base de la rectificación.',409)
        payment.amount=decimal(correction.snapshot['after']['calculation']['payable']);payment.version+=1
        correction.snapshot={**correction.snapshot,'approval':{'actor_id':g.user.id,'name':g.user.name,'demo':True}}
        from .reports import pdf_report
        from .documents import store_document
        from ..models.domain import Intervention
        work=db.session.get(Intervention,cert.work_id)
        content=pdf_report('Anexo de rectificación DEMO',[work.name,f'Certificado {cert.id} · período {cert.period}',correction.reason,f"Original: {correction.snapshot['before']['calculation']['payable']} UYU",f"Rectificado: {correction.snapshot['after']['calculation']['payable']} UYU",f"Diferencia: {correction.snapshot['delta']} UYU",f'Aprobó: {g.user.name} · El certificado y su nota originales permanecen inmutables. Este anexo acompaña el expediente.'],['Código','Descripción','Unidad','Acumulado','Importe','LLSS'],[[l['code'],l['description'],l['unit'],l['accumulated'],l['amount'],l['social']] for l in correction.snapshot['after']['calculation']['lines']])
        document=store_document(work,content,f'rectificacion-{correction.id}.pdf',{'kind':'rectificacion','classification':'reservado'})
        correction.snapshot={**correction.snapshot,'document_id':document.id,'sha256':document.sha256}
    correction.status=payload['status'];correction.approved_by=g.user.id
    history(cert.work_id,'certificado',cert.id,'resolver_rectificacion',target=correction.status,details={'rectification_id':correction.id,'reason':correction.reason,'delta':correction.snapshot['delta']})
