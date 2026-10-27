from ..extensions import db
from ..services import checkout as gateway
from flask import g
from ..services.access import authenticated, work_for
from ..services.errors import require
from .interventions import body
from .workflow import payment_for
from . import api_bp


@api_bp.route('/demo/payment-runs', methods=['GET', 'POST'])
@api_bp.get('/demo/payment-runs/<int:run_id>')
@api_bp.post('/demo/payment-runs/<int:run_id>/advance')
@authenticated
def retired_payment_screen(run_id=None):
    # An already-open browser can still be executing the previous JS bundle.
    # Explain the upgrade instead of exposing a generic English 404 or executing
    # the retired approval chain. No data is read or modified by this response.
    return {'code': 'client_outdated', 'message': 'Actualizamos la pantalla de Pagos. Recargá esta pestaña (Ctrl + F5) para abrir la nueva pasarela.',
            'reload_url': '/pagos'}, 410


@api_bp.get('/payment-orders')
@authenticated
def orders():
    data = gateway.order_rows() if gateway.enabled() else []
    db.session.commit()
    return {'orders': data, 'sandbox': gateway.enabled(), 'can_create_example': gateway.can_operate(),
            'view': 'supplier' if g.user.role == 'empresa' else 'operator' if gateway.can_operate() else 'read_only'}


@api_bp.post('/payment-orders/example')
@authenticated
def example():
    payment, created = gateway.example(body())
    db.session.commit()
    return {'payment_id': payment.id, 'work_id': gateway.payment_work(payment).id}, 201 if created else 200


@api_bp.post('/works/<int:work_id>/payments/<int:payment_id>/checkout')
@authenticated
def create_checkout(work_id, payment_id):
    work = work_for(work_id, lock=True)
    payment = payment_for(work_id, payment_id)
    session, created = gateway.create_session(work, payment)
    db.session.commit()
    return {'session': gateway.detail(session, work, payment)}, 201 if created else 200


@api_bp.get('/checkout/<public_id>')
@authenticated
def show_checkout(public_id):
    require(gateway.enabled(), 'La pasarela de prueba está deshabilitada.', 409)
    session, work, payment = gateway.lock_session(public_id)
    gateway.settle(session, work, payment)
    db.session.commit()
    return {'session': gateway.detail(session, work, payment)}


@api_bp.post('/checkout/<public_id>/authorize')
@authenticated
def authorize(public_id):
    session, work, payment = gateway.lock_session(public_id)
    gateway.authorize(session, work, payment, body())
    db.session.commit()
    return {'session': gateway.detail(session, work, payment)}


@api_bp.post('/checkout/<public_id>/cancel')
@authenticated
def cancel(public_id):
    session, work, payment = gateway.lock_session(public_id)
    gateway.cancel(session, work, payment)
    db.session.commit()
    return {'session': gateway.detail(session, work, payment)}
