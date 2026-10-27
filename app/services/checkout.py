"""Local hosted gateway: authorize a test bank account, then settle server-side.

The client never supplies the result or the amount. Processing survives navigation.
No connection to a bank or third-party gateway is made.
"""
from contextlib import contextmanager
from datetime import date, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from flask import current_app, g
from ..extensions import db
from ..models import User
from ..models.domain import (Assignment, BudgetLine, Certificate, CheckoutSession, Company,
                            Contract, Intervention, Payment, PaymentAttempt, Rectification, now)
from .access import history, work_for, work_query, representation_for
from .errors import require
from .economics import calculate
from .payment_simulator import initiate, resolve
from .reports import certificate_pdfs, pdf_report
from .documents import store_document
from .works import text

OPERATORS = {'super_admin', 'admin', 'direccion_general', 'administrativo', 'director_obra', 'tecnico', 'inspector'}
ACCOUNTS = {
    'operativa': {'id': 'operativa', 'name': 'Cuenta operativa', 'holder': 'Intendencia Demo', 'number': '•••• 1042', 'balance': '1500000.00'},
    'sin_saldo': {'id': 'sin_saldo', 'name': 'Cuenta sin saldo', 'holder': 'Intendencia Demo', 'number': '•••• 0099', 'balance': '0.00'},
}


def enabled():
    return bool(current_app.config['DEMO_ENVIRONMENT'] and current_app.config['DEMO_AUTH_ENABLED'] and g.user.demo)


def is_fixture(work, payment):
    certificate = db.session.get(Certificate, payment.certificate_id)
    return bool(work.demo and payment.demo and work.code.startswith('DEMO-CHECKOUT-')
                and certificate and (certificate.approved_snapshot or {}).get('fixture') is True)


def is_demo_order(work, payment):
    if not payment.demo:
        return False
    if work.demo:
        return True
    # New works are preserved by reset-demo. They can still be synthetic orders
    # when both their creator and awarded company are authenticated demo entities.
    creator = db.session.get(User, work.created_by)
    company = db.session.get(Company, work.company_id)
    return bool(creator and creator.demo and company and company.demo)


def can_operate(work=None, payment=None):
    if not enabled():
        return False
    if work is not None and not is_demo_order(work, payment):
        return False
    if g.user.role in OPERATORS:
        return True
    if g.user.role != 'empresa':
        return False
    company = db.session.get(Company, g.user.company_id)
    if not company or not company.demo or company.status != 'activa':
        return False
    # Supplier presenters may exercise the sandbox, never order payments on
    # ordinary works or access a different company's examples.
    return work is None or (work.company_id == company.id and is_fixture(work, payment))


def require_operator(work=None, payment=None):
    require(enabled(), 'La pasarela de prueba está deshabilitada.', 409, 'demo_disabled')
    require(can_operate(work, payment), 'Este perfil puede consultar este pago. Para probar la pasarela, usá Nuevo pago de prueba.'
            if g.user.role == 'empresa' else 'Este perfil puede consultar pagos, pero no ordenarlos.', 403)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def payment_work(payment):
    return db.session.get(Intervention, db.session.get(Certificate, payment.certificate_id).work_id)


def lock_session(public_id):
    row = CheckoutSession.query.filter_by(public_id=public_id).first()
    require(row, 'Sesión de pago no encontrada.', 404)
    work_id = payment_work(db.session.get(Payment, row.payment_id)).id
    work = work_query().filter_by(id=work_id).populate_existing().with_for_update().first()
    require(work, 'Obra no encontrada.', 404)
    payment = Payment.query.filter_by(id=row.payment_id).populate_existing().with_for_update().one()
    row = CheckoutSession.query.filter_by(id=row.id).populate_existing().with_for_update().one()
    return row, work, payment


@contextmanager
def original_operator(session):
    viewer = g.user
    g.user = db.session.get(User, session.created_by)
    try:
        yield
    finally:
        g.user = viewer


def settle(session, work, payment):
    if session.status == 'created' and utc(session.expires_at) <= now():
        session.status = 'expired'
        session.result_message = 'La sesión venció. Volvé a iniciar el pago.'
    if session.status != 'processing' or utc(session.process_after) > now():
        return
    # This deterministic adapter is the simulated bank callback, not a user decision.
    balance = Decimal(ACCOUNTS[session.account]['balance'])
    attempt = db.session.get(PaymentAttempt, session.attempt_id)
    unchanged = (payment.status == 'contaduria_tesoreria' and payment.version == attempt.payment_version
                 and payment.amount == session.amount and work.company_id == session.company_id)
    approved = unchanged and balance >= session.amount
    message = ('Transferencia procesada correctamente.' if approved else
               'Saldo insuficiente en la cuenta de prueba.' if unchanged else 'La orden cambió durante el pago. Iniciá una nueva sesión.')
    with original_operator(session):
        resolve(work, payment, attempt, {'status': 'aprobada' if approved else 'rechazada' if unchanged else 'cancelada',
                                        'reason': message, 'source_account': ACCOUNTS[session.account]['number'],
                                        'destination_account': '•••• 9087'}, gateway=True)
        history(work.id, 'pasarela', session.id, 'respuesta_automatica', 'processing', 'succeeded' if approved else 'failed',
                {'provider': 'DemoPay', 'event': 'bank_result', 'session': session.public_id, 'demo': True})
    session.status = 'succeeded' if approved else 'failed'
    session.result_code = 'approved' if approved else 'insufficient_funds' if unchanged else 'order_changed'
    session.result_message = message
    session.closing_balance = balance-session.amount if approved else balance
    db.session.flush()


def create_session(work, payment):
    require_operator(work, payment)
    require(is_demo_order(work, payment), 'La pasarela sólo admite órdenes ficticias.', 409)
    rows = CheckoutSession.query.filter_by(payment_id=payment.id).order_by(CheckoutSession.id.desc()).populate_existing().with_for_update().all()
    for session in rows:
        settle(session, work, payment)
        if session.status in ('created', 'processing'):
            require(session.created_by == g.user.id, 'Otra cuenta está procesando esta orden.', 409)
            return session, False
    require(payment.status == 'contaduria_tesoreria', 'Esta orden aún no está disponible para pagar o ya fue pagada.', 409)
    require(not PaymentAttempt.query.filter_by(payment_id=payment.id, status='pendiente').first(), 'Existe una operación anterior pendiente en esta orden.', 409)
    require(not Rectification.query.filter_by(certificate_id=payment.certificate_id, status='solicitada').first(), 'La orden tiene una rectificación pendiente.', 409)
    require(work.company_id and payment.amount > 0, 'La orden requiere un destinatario e importe válidos.', 409)
    session = CheckoutSession(payment_id=payment.id, created_by=g.user.id, payment_version=payment.version,
                              company_id=work.company_id, amount=payment.amount, expires_at=now()+timedelta(minutes=15))
    db.session.add(session)
    db.session.flush()
    history(work.id, 'pasarela', session.id, 'abrir_checkout', target='created', details={'demo': True})
    return session, True


def authorize(session, work, payment, payload):
    require_operator(work, payment)
    require(session.created_by == g.user.id, 'La sesión pertenece a otra cuenta.', 403)
    settle(session, work, payment)
    if session.status in ('processing', 'succeeded', 'failed'):
        return session
    require(session.status == 'created', 'La sesión está cerrada. Iniciá nuevamente el pago.', 409)
    account = payload.get('account')
    require(isinstance(account, str) and account in ACCOUNTS, 'Seleccioná una cuenta de prueba.')
    require(payload.get('code') == '123456', 'El código de autorización de prueba es 123456.')
    require(payment.version == session.payment_version and payment.amount == session.amount and work.company_id == session.company_id,
            'La orden cambió. Volvé a la lista de pagos.', 409)
    attempt, _ = initiate(work, payment, {'version': session.payment_version, 'idempotency_key': 'checkout-'+session.public_id,
                                        'confirm_demo': True}, gateway=True)
    session.account, session.attempt_id, session.status = account, attempt.id, 'processing'
    session.process_after = now()+timedelta(seconds=current_app.config.get('CHECKOUT_PROCESSING_DELAY', 2))
    history(work.id, 'pasarela', session.id, 'autorizar', 'created', 'processing', {'account': account, 'demo': True})
    return session


def cancel(session, work, payment):
    require_operator(work, payment)
    require(session.created_by == g.user.id, 'La sesión pertenece a otra cuenta.', 403)
    if session.status == 'cancelled':
        return
    require(session.status == 'created', 'La operación ya se envió. Esperá su resultado.', 409)
    session.status = 'cancelled'
    session.result_message = 'Cancelaste el pago antes de enviarlo.'
    history(work.id, 'pasarela', session.id, 'cancelar', 'created', 'cancelled', {'demo': True})


def detail(session, work, payment):
    cert = db.session.get(Certificate, payment.certificate_id)
    company = db.session.get(Company, session.company_id)
    attempt = db.session.get(PaymentAttempt, session.attempt_id) if session.attempt_id else None
    return {'id': session.public_id, 'status': session.status, 'amount': str(session.amount), 'currency': 'UYU',
            'work_id': work.id, 'work_name': work.name, 'payment_id': payment.id, 'reference': payment.reference,
            'invoice_number': cert.invoice_number, 'company_name': company.name, 'destination': 'Cuenta de prueba •••• 9087',
            'account': session.account, 'accounts': list(ACCOUNTS.values()), 'closing_balance': str(session.closing_balance) if session.closing_balance is not None else None,
            'transaction': attempt.reference if attempt else None, 'receipt_id': attempt.receipt_id if attempt else None,
            'result_code': session.result_code, 'message': session.result_message,
            'presentation_mode': db.session.get(User, session.created_by).role == 'empresa',
            'expires_at': session.expires_at.isoformat(), 'can_authorize': can_operate(work, payment) and session.created_by == g.user.id,
            'return_url': '/pagos', 'checkout_url': '/pasarela/'+session.public_id}


def order_rows():
    rows = db.session.query(Payment, Certificate, Intervention, Company).join(Certificate, Certificate.id == Payment.certificate_id).join(
        Intervention, Intervention.id == Certificate.work_id).join(Company, Company.id == Intervention.company_id).filter(
        Intervention.id.in_(work_query().with_entities(Intervention.id))).order_by(Intervention.id).all()
    output = []
    for payment, cert, work, company in rows:
        # Use the same lock order as authorization and polling.
        latest = CheckoutSession.query.filter_by(payment_id=payment.id).order_by(CheckoutSession.id.desc()).first()
        if latest and latest.status in ('created', 'processing'):
            latest, work, payment = lock_session(latest.public_id)
            settle(latest, work, payment)
        pending = PaymentAttempt.query.filter_by(payment_id=payment.id, status='pendiente').first()
        state = 'paid' if payment.status == 'pagado' else 'processing' if pending and latest and latest.status == 'processing' else 'in_review' if pending else 'ready' if payment.status == 'contaduria_tesoreria' else 'in_review'
        correction = Rectification.query.filter_by(certificate_id=cert.id, status='solicitada').first()
        if correction:
            state = 'in_review'
        confirmation = payment.confirmation or {}
        reserved = bool(latest and latest.status in ('created', 'processing') and latest.created_by != g.user.id)
        allowed = can_operate(work, payment)
        unavailable_reason = ('Otra persona tiene este pago abierto. Podés crear un nuevo pago de prueba.' if reserved else
                              'Este pago lo realiza Tesorería.' if g.user.role == 'empresa' and not allowed else
                              'Este perfil tiene acceso de consulta.' if not allowed else None)
        output.append({'id': payment.id, 'work_id': work.id, 'work_name': work.name, 'company_name': company.name,
                       'reference': payment.reference, 'invoice_number': cert.invoice_number, 'amount': str(payment.amount), 'status': state,
                       'is_example': is_fixture(work, payment), 'presentation_mode': g.user.role == 'empresa',
                       'can_pay': allowed and state == 'ready' and not reserved,
                       'unavailable_reason': unavailable_reason,
                       'checkout_id': latest.public_id if latest else None,
                       'can_resume': bool(allowed and latest and latest.created_by == g.user.id and latest.status in ('created', 'processing')),
                       'checkout_status': latest.status if latest else None,
                       'receipt_id': (confirmation.get('document_ids') or [None])[0], 'date': confirmation.get('date')})
    return sorted(output, key=lambda r: (not r['is_example'], -r['id']))


def example(payload):
    """Load a ready-made fictional order, without executing approval transitions."""
    require_operator()
    key = text(payload.get('idempotency_key'), 'Clave del ejemplo', 80)
    require(len(key) >= 16, 'La clave del ejemplo debe tener al menos 16 caracteres.')
    User.query.filter_by(id=g.user.id).with_for_update().first()
    existing = Certificate.query.filter_by(idempotency_key='checkout-fixture-'+key).first()
    if existing:
        work = work_for(existing.work_id)
        require(work.created_by == g.user.id, 'Clave de ejemplo utilizada por otra cuenta.', 409)
        return Payment.query.filter_by(certificate_id=existing.id).one(), False
    if g.user.role == 'empresa':
        representation_for(g.user)
        company = db.session.get(Company, g.user.company_id)
    else:
        company = Company.query.filter_by(rut='DEMO-A', demo=True).first()
    users = {k: User.query.filter_by(email=k+'@demo.invalid', demo=True, is_active=True).first() for k in ('director', 'general', 'tecnico', 'inspector')}
    supplier = g.user if g.user.role == 'empresa' else User.query.filter_by(company_id=company.id if company else None, role='empresa', demo=True, is_active=True).first()
    require(company and supplier and all(users.values()), 'Faltan las cuentas de demostración.', 409)
    code = 'DEMO-CHECKOUT-'+uuid4().hex[:8].upper()
    today = date.today()
    work = Intervention(code=code, name='Plaza de los Olivos · Pago de prueba', locality='Minas', stage='obra', status='en_ejecucion',
                        description='Orden y antecedentes ficticios precargados para probar exclusivamente el pago electrónico.',
                        company_id=company.id, unit_id=users['director'].unit_id, created_by=g.user.id, budget='1220000.00',
                        start_date=today-timedelta(days=30), end_date=today+timedelta(days=90), public=False, demo=True)
    db.session.add(work); db.session.flush()
    assigned = {u.id: u for u in [g.user, users['director'], users['tecnico'], users['inspector']]}
    db.session.add_all(Assignment(work_id=work.id, user_id=u.id, role=u.role, contact={}) for u in assigned.values())
    contract = Contract(work_id=work.id, version=1, kind='contractual', status='aprobado', company_id=company.id, number=code+'-CON',
                        amount='1220000.00', rules={'iva_rate': '0.22', 'social_payment': 'separado'}, reason='Contrato sintético precargado de sandbox.')
    db.session.add(contract); db.session.flush()
    line = BudgetLine(contract_id=contract.id, code='1', description='Pavimento e iluminación de demostración', unit='global', quantity=1, unit_price=1000000, social_rate=0)
    db.session.add(line); db.session.flush()
    calc = calculate([line], {'1': '25'}, {}, contract.rules, 'periodo')
    period_date = today.replace(day=1)-timedelta(days=1)
    invoice_number = code+'-F01'
    invoice = store_document(work, pdf_report('Factura FICTICIA · Orden de prueba', [f'Emisor: {company.name}', f'Factura: {invoice_number}',
                             'Base: UYU 250000.00 · IVA: UYU 55000.00 · Total: UYU 305000.00', 'Antecedente sintético precargado.']),
                             'factura-pasarela-demo.pdf', {'kind': 'factura', 'classification': 'reservado'})
    cert = Certificate(work_id=work.id, contract_id=contract.id, period=period_date.strftime('%Y-%m'), start_date=period_date.replace(day=1), end_date=period_date,
                       mode='periodo', status='aprobado', input={'advances': {'1': '25'}, 'icc_current': None}, calculation=calc, invoice_id=invoice.id,
                       invoice_number=invoice_number, initial_by=users['director'].id, final_by=users['general'].id, created_by=supplier.id,
                       idempotency_key='checkout-fixture-'+key)
    db.session.add(cert); db.session.flush()
    cert.approved_snapshot = {'certificate_id': cert.id, 'period': cert.period, 'dates': [cert.start_date.isoformat(), cert.end_date.isoformat()],
                              'contract': contract.to_dict(), 'calculation': calc, 'invoice': invoice.to_dict(), 'invoice_number': invoice_number,
                              'approvals': [{'role': 'Dirección de Obra (fixture)', 'actor_id': users['director'].id, 'name': users['director'].name},
                                            {'role': 'Dirección General (fixture)', 'actor_id': users['general'].id, 'name': users['general'].name}],
                              'demo': True, 'fixture': True, 'work': {'name': work.name}}
    certificate_pdfs(cert, work, commit=False)
    payment = Payment(certificate_id=cert.id, reference='DEMO-ORD-'+code.removeprefix('DEMO-CHECKOUT-'), status='contaduria_tesoreria', amount=calc['payable'], demo=True)
    db.session.add(payment); db.session.flush()
    history(work.id, 'sandbox', payment.id, 'cargar_orden_ficticia', target='lista_para_pagar', details={'demo': True, 'fixture': True})
    return payment, True
