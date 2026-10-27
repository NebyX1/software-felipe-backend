import calendar
import copy
from datetime import date
import re
from flask import g
from ..extensions import db
from ..models import User
from ..models.domain import Contract, BudgetLine, Certificate, CertificateRevision, Payment, Document, Intervention
from .access import roles, history, check_version, document_for
from .economics import calculate
from .errors import require
from .works import iso_date, text


def previous_advances(work_id):
    previous = {}
    from .rectification import effective_snapshot
    for certificate in Certificate.query.filter_by(work_id=work_id, status='aprobado').order_by(Certificate.period):
        for line in effective_snapshot(certificate)['calculation']['lines']:
            previous[line['code']] = line['accumulated']
    return previous


def calculation(work_id, contract, payload):
    lines = BudgetLine.query.filter_by(contract_id=contract.id).order_by(BudgetLine.id).all()
    from .rectification import effective_snapshot
    quantities={}
    for c in Certificate.query.filter_by(work_id=work_id,status='aprobado').order_by(Certificate.period):
        for l in effective_snapshot(c)['calculation']['lines']:
            if 'accumulated_quantity' in l:quantities[l['code']]=l['accumulated_quantity']
    return calculate(lines, payload.get('advances', {}), previous_advances(work_id), contract.rules, payload.get('mode', 'periodo'), payload.get('icc_current'),quantities)


def new_certificate(work, payload):
    roles('empresa')
    require(work.stage == 'obra', 'La intervención debe estar en ejecución.', 409)
    from ..models.domain import Rectification
    require(not Rectification.query.join(Certificate,Rectification.certificate_id==Certificate.id).filter(Certificate.work_id==work.id,Rectification.status=='solicitada').count(),'Resolvé la rectificación pendiente antes del siguiente período.',409)
    period = payload.get('period', '')
    require(isinstance(period, str) and re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period), 'Período debe ser AAAA-MM.')
    year, month = map(int, period.split('-'))
    require(year >= 1, 'El año del período debe ser válido.')
    start = iso_date(payload.get('start_date')) or date(year, month, 1)
    end = iso_date(payload.get('end_date')) or date(year, month, calendar.monthrange(year, month)[1])
    require(start <= end and start.strftime('%Y-%m') == period and end.strftime('%Y-%m') == period, 'Las fechas deben pertenecer al período seleccionado.')
    key = text(payload.get('idempotency_key', ''), 'Clave de operación', 100)
    require(len(key) >= 16, 'La clave de operación debe tener al menos 16 caracteres.')
    existing = Certificate.query.filter_by(idempotency_key=key).first()
    values = {'advances': payload.get('advances', {}), 'icc_current': payload.get('icc_current')}
    if existing:
        require(existing.work_id == work.id and existing.created_by == g.user.id and existing.period == period and existing.start_date == start and existing.end_date == end and existing.mode == payload.get('mode', 'periodo') and existing.input == values, 'Clave reutilizada con datos distintos.', 409, 'idempotency_conflict')
        return existing, False
    require(not Certificate.query.filter_by(work_id=work.id, period=period).first(), 'Ya existe una certificación de este período.', 409, 'duplicate_period')
    require(not Certificate.query.filter_by(work_id=work.id).filter(Certificate.status != 'aprobado').first(), 'Completá la certificación pendiente antes de iniciar otro período.', 409)
    latest = db.session.query(db.func.max(Certificate.period)).filter_by(work_id=work.id).scalar()
    require(not latest or period > latest, 'La certificación debe ser posterior a los períodos existentes.')
    contract = Contract.query.filter_by(work_id=work.id, kind='contractual', status='aprobado', company_id=g.user.company_id).first()
    require(contract, 'No hay contrato vigente para tu empresa.', 409)
    result = calculation(work.id, contract, payload)
    cert = Certificate(work_id=work.id, contract_id=contract.id, period=period, start_date=start, end_date=end, mode=payload.get('mode', 'periodo'), input=values, calculation=result, created_by=g.user.id, idempotency_key=key)
    db.session.add(cert)
    db.session.flush()
    save_revision(cert)
    history(work.id, 'certificado', cert.id, 'crear', target='borrador')
    return cert, True


def save_revision(cert):
    db.session.add(CertificateRevision(certificate_id=cert.id, revision=cert.revision, snapshot=copy.deepcopy({'mode': cert.mode, 'input': cert.input, 'calculation': cert.calculation, 'status': cert.status}), actor_id=g.user.id))


def revise(cert, payload):
    roles('empresa')
    require(cert.status in ('borrador', 'observado'), 'El certificado está cerrado a modificaciones.', 409)
    check_version(cert, payload)
    cert.mode = payload.get('mode', cert.mode)
    cert.input = {'advances': payload.get('advances', cert.input['advances']), 'icc_current': payload.get('icc_current', cert.input.get('icc_current'))}
    contract = db.session.get(Contract, cert.contract_id)
    cert.calculation = calculation(cert.work_id, contract, {**cert.input, 'mode': cert.mode})
    cert.revision += 1
    save_revision(cert)
    history(cert.work_id, 'certificado', cert.id, 'subsanar', details={'revision': cert.revision})


def transition(cert, payload):
    previous = cert.status
    target = payload.get('status')
    check_version(cert, payload)
    allowed = {
        ('borrador', 'presentado'): {'empresa'},
        ('observado', 'presentado'): {'empresa'},
        ('presentado', 'observado'): {'director_obra', 'admin', 'super_admin'},
        ('presentado', 'aprobacion_inicial'): {'director_obra', 'admin', 'super_admin'},
        ('aprobacion_inicial', 'facturado'): {'empresa'},
        ('facturado', 'observado'): {'direccion_general', 'admin', 'super_admin'},
        ('facturado', 'aprobado'): {'direccion_general', 'admin', 'super_admin'},
    }
    require((previous, target) in allowed, 'El circuito no permite ese paso.', 409, 'invalid_transition')
    roles(*allowed[(previous, target)])
    comment = payload.get('comment', '')
    if target == 'observado':
        text(comment, 'Observación')
        cert.initial_by = None
        cert.invoice_id, cert.invoice_number = None, None
    if target == 'aprobacion_inicial':
        require(cert.calculation['lines'], 'Falta rubrado de certificación.')
        from .economics import decimal
        require(decimal(cert.calculation['base']) > 0, 'La certificación debe tener avance positivo.')
        cert.initial_by = g.user.id
    if target == 'facturado':
        invoice = document_for(payload.get('invoice_id'))
        require(invoice.work_id == cert.work_id and invoice.mime == 'application/pdf' and invoice.company_id == g.user.company_id and invoice.kind == 'factura', 'La factura debe ser PDF de esta empresa y obra.')
        cert.invoice_id, cert.invoice_number = invoice.id, text(payload.get('invoice_number', ''), 'Número de factura', 100)
    if target == 'aprobado':
        require(cert.invoice_id and cert.initial_by, 'Falta factura o aprobación inicial.', 409)
        invoice = db.session.get(Document, cert.invoice_id)
        require(invoice and invoice.status != 'eliminado', 'Factura no disponible.', 409)
        contract = db.session.get(Contract, cert.contract_id)
        recomputed = calculation(cert.work_id, contract, {**cert.input, 'mode': cert.mode})
        def comparable(value):
            return {**value,'lines':[{k:v for k,v in l.items() if k not in ('previous_quantity','accumulated_quantity')} for l in value['lines']]}
        require(comparable(recomputed) == comparable(cert.calculation), 'El acumulado cambió: se requiere nueva revisión.', 409)
        cert.calculation=recomputed  # Metadata-only engine upgrade; monetary review remains identical.
        cert.final_by = g.user.id
        from ..infrastructure.institutional import DemoInstitutionalAdapter
        adapter=DemoInstitutionalAdapter()
        initial = db.session.get(User, cert.initial_by)
        cert.approved_snapshot = copy.deepcopy({'certificate_id': cert.id, 'period': cert.period, 'dates': [cert.start_date.isoformat(), cert.end_date.isoformat()], 'contract': contract.to_dict(), 'calculation': cert.calculation, 'invoice': invoice.to_dict(), 'invoice_number': cert.invoice_number, 'approvals': [{'role': 'Dirección de Obra', 'actor_id': initial.id, 'name': initial.name}, {'role': 'Dirección General', 'actor_id': g.user.id, 'name': g.user.name}], 'demo': True})
        cert.approved_snapshot={**cert.approved_snapshot,'work':{'name':db.session.get(Intervention,cert.work_id).name},'signature_boundary':adapter.acknowledge(g.user.id,f'certificate:{cert.id}'),'dossier_boundary':adapter.register(cert.id)}
        db.session.add(Payment(certificate_id=cert.id, reference=adapter.register(cert.id)['reference'], amount=cert.calculation['payable'], demo=True))
    cert.status = target
    history(cert.work_id, 'certificado', cert.id, 'transicion', previous, target, {'comment': comment, 'revision': cert.revision})


def payment_transition(work, payment, payload):
    roles('administrativo', 'direccion_general', 'admin', 'super_admin')
    require(payment.demo, 'Este adaptador sólo registra pagos ficticios.', 409)
    from flask import current_app
    require(current_app.config['DEMO_ENVIRONMENT'] and current_app.config['DEMO_AUTH_ENABLED'], 'Pagos ficticios sólo habilitados en demo.', 409)
    from ..models.domain import PaymentAttempt
    require(not PaymentAttempt.query.filter_by(payment_id=payment.id, status='pendiente').first(), 'Resolvé la transferencia pendiente antes de modificar el expediente.', 409)
    from ..models.domain import Rectification
    require(not Rectification.query.filter_by(certificate_id=payment.certificate_id,status='solicitada').count(),'Resolvé la rectificación antes de tramitar el expediente.',409)
    check_version(payment, payload)
    previous = payment.status
    sequence = ['expediente', 'hacienda', 'secretaria_general', 'resolucion', 'contaduria_tesoreria', 'pagado']
    index = sequence.index(previous)
    require(index < len(sequence)-1 and payload.get('status') == sequence[index+1], 'El pago debe respetar el orden del expediente.', 409)
    if payload['status'] == 'resolucion':
        roles('direccion_general', 'admin', 'super_admin')
    comment = text(payload.get('comment', ''), 'Actuación administrativa')
    if payload['status'] == 'hacienda':
        require(payload.get('budget_available') is True, 'Hacienda debe confirmar disponibilidad presupuestal.')
    ids = payload.get('document_ids', [])
    require(all(document_for(i).work_id == work.id for i in ids), 'Adjuntos de otro expediente.')
    if payload['status'] in ('resolucion', 'pagado'):
        require(ids, 'Adjuntá resolución o comprobante ficticio según el paso.')
    if payload['status'] == 'pagado':
        require(payload.get('confirm_demo') is True, 'Confirmá expresamente que el pago es ficticio.')
        from ..infrastructure.institutional import DemoInstitutionalAdapter
        payment.confirmation = {**DemoInstitutionalAdapter().confirm(g.user.id,payment.reference), 'date': date.today().isoformat(), 'comment': comment, 'document_ids': ids}
    payment.status = payload['status']
    history(work.id, 'pago', payment.id, 'pase', previous, payment.status, {'comment': comment, 'document_ids': ids, 'demo': True})
