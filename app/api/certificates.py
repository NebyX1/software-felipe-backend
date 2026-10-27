from flask import request, current_app
from ..extensions import db
from ..models.domain import Certificate, CertificateRevision, Contract, Payment,Rectification
from ..services.access import authenticated, work_for
from ..services.errors import require
from ..services.certification import new_certificate, revise, transition, payment_transition, calculation
from ..services.reports import certificate_pdfs
from .interventions import body
from . import api_bp


@api_bp.route('/works/<int:work_id>/certificates', methods=['GET', 'POST'])
@authenticated
def certificates(work_id):
    work = work_for(work_id, request.method == 'POST')
    if request.method == 'POST':
        cert, created = new_certificate(work, body())
        db.session.commit()
        return {'certificate': cert.to_dict()}, 201 if created else 200
    return {'certificates': [c.to_dict() for c in Certificate.query.filter_by(work_id=work_id).order_by(Certificate.period.desc())]}


@api_bp.post('/works/<int:work_id>/certificates/preview')
@authenticated
def certificate_preview(work_id):
    work_for(work_id)
    contract = Contract.query.filter_by(work_id=work_id, kind='contractual', status='aprobado').first()
    require(contract, 'Falta contrato vigente.', 409)
    return {'calculation': calculation(work_id, contract, body())}


def cert_for(work_id, certificate_id):
    cert = Certificate.query.filter_by(work_id=work_id, id=certificate_id).with_for_update().first()
    require(cert, 'Certificación no encontrada.', 404)
    return cert


@api_bp.patch('/works/<int:work_id>/certificates/<int:certificate_id>')
@authenticated
def revision(work_id, certificate_id):
    work_for(work_id, True)
    cert = cert_for(work_id, certificate_id)
    revise(cert, body())
    db.session.commit()
    return {'certificate': cert.to_dict()}


@api_bp.get('/works/<int:work_id>/certificates/<int:certificate_id>/revisions')
@authenticated
def revisions(work_id, certificate_id):
    work_for(work_id)
    cert_for(work_id, certificate_id)
    return {'revisions': [r.to_dict() for r in CertificateRevision.query.filter_by(certificate_id=certificate_id).order_by(CertificateRevision.revision)]}


@api_bp.post('/works/<int:work_id>/certificates/<int:certificate_id>/transition')
@authenticated
def certificate_transition(work_id, certificate_id):
    work = work_for(work_id, True)
    cert = cert_for(work_id, certificate_id)
    transition(cert, body())
    db.session.commit()
    if cert.status == 'aprobado':
        try:
            certificate_pdfs(cert, work)
        except Exception:
            db.session.rollback()
            current_app.logger.error('Certificate PDF pending id=%s', cert.id)
    return {'certificate': cert.to_dict()}


@api_bp.post('/works/<int:work_id>/certificates/<int:certificate_id>/pdf/retry')
@authenticated
def retry_pdf(work_id, certificate_id):
    work = work_for(work_id, True)
    cert = cert_for(work_id, certificate_id)
    require(cert.status == 'aprobado', 'Certificado sin aprobación final.', 409)
    certificate_pdfs(cert, work)
    return {'certificate': cert.to_dict()}


@api_bp.get('/works/<int:work_id>/payments')
@authenticated
def payments(work_id):
    work_for(work_id)
    return {'payments': [p.to_dict() for p in Payment.query.join(Certificate, Payment.certificate_id == Certificate.id).filter(Certificate.work_id == work_id)]}


@api_bp.post('/works/<int:work_id>/payments/<int:payment_id>/transition')
@authenticated
def payment_step(work_id, payment_id):
    work = work_for(work_id, True)
    payment = Payment.query.join(Certificate, Payment.certificate_id == Certificate.id).filter(Payment.id == payment_id, Certificate.work_id == work_id).with_for_update().first()
    require(payment, 'Expediente no encontrado.', 404)
    payment_transition(work, payment, body())
    db.session.commit()
    return {'payment': payment.to_dict()}


@api_bp.route('/works/<int:work_id>/certificates/<int:certificate_id>/rectifications',methods=['GET','POST'])
@authenticated
def corrections(work_id,certificate_id):
    work_for(work_id,request.method=='POST');cert=cert_for(work_id,certificate_id)
    if request.method=='GET':
        return {'rectifications':[r.to_dict() for r in Rectification.query.filter_by(certificate_id=cert.id)]}
    from ..services.rectification import request_correction
    correction=request_correction(cert,body());db.session.commit()
    return {'rectification':correction.to_dict()},201


@api_bp.post('/works/<int:work_id>/certificates/<int:certificate_id>/rectifications/<int:correction_id>/resolve')
@authenticated
def correction_resolve(work_id,certificate_id,correction_id):
    work_for(work_id,True);cert=cert_for(work_id,certificate_id)
    correction=Rectification.query.filter_by(id=correction_id,certificate_id=cert.id).with_for_update().first()
    require(correction,'Rectificación no encontrada.',404)
    from ..services.rectification import resolve
    resolve(cert,correction,body());db.session.commit()
    return {'rectification':correction.to_dict()}
