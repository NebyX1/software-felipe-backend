"""Internal demo gateway. No network, bank credentials or movement of funds."""
from uuid import uuid4
from flask import g, current_app
from ..extensions import db
from ..models.domain import PaymentAttempt, Rectification, Document, Company, now
from ..infrastructure.storage import get_document_storage
from .access import roles, check_version, history
from .errors import require
from .works import text
from .reports import pdf_report


def enabled(payment, *, gateway=False):
    if not gateway:
        roles('administrativo', 'direccion_general', 'admin', 'super_admin')
    else:
        require(g.user.demo, 'La pasarela sólo admite cuentas de prueba.', 403)
    require(current_app.config['DEMO_ENVIRONMENT'] and current_app.config['DEMO_AUTH_ENABLED'] and payment.demo,
            'El simulador está habilitado exclusivamente en demostración.', 409)
    require(not Rectification.query.filter_by(certificate_id=payment.certificate_id, status='solicitada').first(),
            'Resolvé la rectificación antes del pago.', 409)


def initiate(work, payment, payload, *, gateway=False):
    enabled(payment, gateway=gateway)
    require(payload.get('confirm_demo') is True, 'Confirmá que la transferencia es ficticia.')
    key = text(payload.get('idempotency_key'), 'Clave de operación', 100)
    existing = PaymentAttempt.query.filter_by(idempotency_key=key).first()
    if existing:
        require(existing.payment_id == payment.id and existing.actor_id == g.user.id,
                'Clave de operación reutilizada para otra transferencia.', 409)
        return existing, False
    require(payment.status == 'contaduria_tesoreria', 'Completá el circuito hasta Contaduría/Tesorería.', 409)
    require(not PaymentAttempt.query.filter_by(payment_id=payment.id, status='pendiente').first(),
            'La transferencia ya está pendiente de respuesta.', 409)
    check_version(payment, payload)
    require(work.company_id and payment.amount > 0, 'Falta destinatario o importe válido.', 409)
    attempt = PaymentAttempt(payment_id=payment.id, reference='SIM-'+uuid4().hex[:16].upper(),
                             idempotency_key=key, amount=payment.amount, company_id=work.company_id,
                             payment_version=payment.version, actor_id=g.user.id)
    db.session.add(attempt)
    db.session.flush()
    history(work.id, 'pago', payment.id, 'transferencia_iniciada', payment.status, 'pendiente',
            {'transaction': attempt.reference, 'amount': str(attempt.amount), 'currency': 'UYU', 'demo': True})
    return attempt, True


def resolve(work, payment, attempt, payload, *, gateway=False):
    enabled(payment, gateway=gateway)
    target = payload.get('status')
    require(target in ('aprobada', 'rechazada', 'cancelada'), 'Respuesta del simulador inválida.')
    if attempt.status != 'pendiente':
        require(attempt.status == target, 'La respuesta de esta operación ya fue registrada.', 409)
        return attempt
    require(target == 'cancelada' or (payment.status == 'contaduria_tesoreria' and payment.version == attempt.payment_version
            and payment.amount == attempt.amount and work.company_id == attempt.company_id),
            'Cambió el expediente. Cancelá la operación pendiente y revisá sus datos.', 409)
    attempt.status, attempt.resolved_at = target, now()
    attempt.reason = text(payload.get('reason', 'Respuesta de la pasarela de demostración'), 'Resultado', 250)
    payment.version += 1
    if target == 'aprobada':
        company = db.session.get(Company, attempt.company_id)
        binary = pdf_report('Comprobante de transferencia electrónica SIMULADA', [
            'SIMULADOR INTERNO · No se enviaron fondos ni solicitudes al banco.',
            *(['Pasarela: DemoPay · Entorno de prueba', 'Ordenante: Intendencia Demo',
               f"Cuenta de origen ficticia: {payload.get('source_account')}",
               f"Cuenta de destino ficticia: {payload.get('destination_account')}"] if gateway else []),
            f'Operación: {attempt.reference}', f'Expediente: {payment.reference}',
            f'Obra: {work.code} · {work.name}', f'Empresa de destino: {company.name}',
            f'Importe confirmado: UYU {attempt.amount}', f'Fecha: {attempt.resolved_at.isoformat()}',
            f'Operador: {g.user.name}', f'Resultado: {attempt.reason}',
        ])
        key, digest = get_document_storage().put(binary)
        receipt = Document(work_id=work.id, name=f'comprobante-{attempt.reference}.pdf', kind='comprobante_pago',
                           stage=work.stage, classification='reservado', company_id=work.company_id,
                           author_id=g.user.id, storage_key=key, sha256=digest, mime='application/pdf',
                           size=len(binary), status='validado')
        db.session.add(receipt)
        db.session.flush()
        attempt.receipt_id = receipt.id
        payment.status = 'pagado'
        payment.confirmation = {'transaction': attempt.reference, 'date': attempt.resolved_at.isoformat(),
                                'amount': str(attempt.amount), 'currency': 'UYU', 'fictitious': True,
                                'bank_transfer': False, 'origin': 'demopay_sandbox' if gateway else 'simulador_interno', 'document_ids': [receipt.id]}
    history(work.id, 'pago', payment.id, 'transferencia_'+target, 'pendiente', target,
            {'transaction': attempt.reference, 'reason': attempt.reason, 'demo': True})
    return attempt
