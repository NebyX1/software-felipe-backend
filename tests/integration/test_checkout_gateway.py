"""Hosted gateway: server outcomes, protected receipts and duplicate-submit safety."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from uuid import uuid4
from pypdf import PdfReader
from app.extensions import db
from app.models.domain import CheckoutSession, Payment, PaymentAttempt, History, Intervention, Company, now
from app.models import User
from .test_obras_flows import request


def fixture(client, login):
    payload = {'idempotency_key': str(uuid4())}
    result = request(client, login, 'tecnico', 'post', '/payment-orders/example', payload, 201)
    assert request(client, login, 'tecnico', 'post', '/payment-orders/example', payload) == result
    return result


def checkout(client, login, order, status=201):
    return request(client, login, 'tecnico', 'post', f"/works/{order['work_id']}/payments/{order['payment_id']}/checkout", {}, status).get('session')


def authorize(client, login, session, account='operativa', **extra):
    return request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/authorize", {'account': account, 'code': '123456', **extra})['session']


def finish(client, login, app, session):
    with app.app_context():
        row = CheckoutSession.query.filter_by(public_id=session['id']).one()
        row.process_after = now()-timedelta(seconds=1)
        db.session.commit()
    return request(client, login, 'tecnico', 'get', f"/checkout/{session['id']}")['session']


def test_checkout_success_fixed_amount_receipt_and_reload(client, login, app):
    order = fixture(client, login)
    rows = request(client, login, 'tecnico', 'get', '/payment-orders')['orders']
    row = next(r for r in rows if r['id'] == order['payment_id'])
    assert row['status'] == 'ready' and row['amount'] == '305000.00'
    session = checkout(client, login, order)
    assert checkout(client, login, order, 200)['id'] == session['id']
    with app.app_context():
        assert PaymentAttempt.query.filter_by(payment_id=order['payment_id']).count() == 0
        # Preparing the fixture must not impersonate institution approval actions.
        events = History.query.filter_by(work_id=order['work_id']).all()
        assert all(e.resource in ('sandbox', 'pasarela', 'documento') for e in events)
    session = authorize(client, login, session, amount='0.01', result='rechazada', balance='0.00')
    assert session['status'] == 'processing' and session['amount'] == '305000.00'
    assert authorize(client, login, session)['id'] == session['id']
    # An admin cannot overwrite a gateway-owned transaction through the legacy API.
    with app.app_context():
        attempt_id = PaymentAttempt.query.filter_by(payment_id=order['payment_id']).one().id
    request(client, login, 'admin', 'post', f"/works/{order['work_id']}/payments/{order['payment_id']}/attempts/{attempt_id}/resolve", {'status': 'aprobada', 'reason': 'Manual'}, 409)
    session = finish(client, login, app, session)
    assert session['status'] == 'succeeded' and session['result_code'] == 'approved'
    assert session['closing_balance'] == '1195000.00' and session['receipt_id']
    assert request(client, login, 'tecnico', 'get', f"/checkout/{session['id']}")['session']['receipt_id'] == session['receipt_id']
    assert authorize(client, login, session)['receipt_id'] == session['receipt_id']
    receipt = client.get(f"/api/documents/{session['receipt_id']}/download", headers=login('tecnico'))
    assert receipt.status_code == 200 and receipt.data.startswith(b'%PDF')
    pdf = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(receipt.data)).pages)
    assert all(value in pdf for value in ('SIMULADA', 'DemoPay', '305000.00', 'Empresa Demo A', session['transaction']))
    with app.app_context():
        assert PaymentAttempt.query.filter_by(payment_id=order['payment_id']).count() == 1
        payment = db.session.get(Payment, order['payment_id'])
        assert payment.status == 'pagado' and payment.confirmation['origin'] == 'demopay_sandbox'
    checkout(client, login, order, 409)  # Already paid, no second transfer.


def test_checkout_insufficient_balance_retry(client, login, app):
    order = fixture(client, login)
    session = checkout(client, login, order)
    session = authorize(client, login, session, 'sin_saldo', result='aprobada', balance='99999999')
    session = finish(client, login, app, session)
    assert session['status'] == 'failed' and session['result_code'] == 'insufficient_funds'
    assert not session['receipt_id'] and session['closing_balance'] == '0.00'
    with app.app_context():
        payment = db.session.get(Payment, order['payment_id'])
        assert payment.status == 'contaduria_tesoreria' and not payment.confirmation
    retry = checkout(client, login, order)
    assert retry['id'] != session['id']
    retry = finish(client, login, app, authorize(client, login, retry))
    assert retry['status'] == 'succeeded'
    with app.app_context():
        assert [a.status for a in PaymentAttempt.query.filter_by(payment_id=order['payment_id']).order_by(PaymentAttempt.id)] == ['rechazada', 'aprobada']


def test_checkout_invalid_code_cancel_and_expiry(client, login, app):
    order = fixture(client, login)
    session = checkout(client, login, order)
    for payload in ({'account': 'operativa', 'code': '000000'}, {'account': 'inventada', 'code': '123456'}, {'account': [], 'code': '123456'}):
        request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/authorize", payload, 422)
    with app.app_context():
        assert PaymentAttempt.query.filter_by(payment_id=order['payment_id']).count() == 0
    cancelled = request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/cancel")['session']
    assert cancelled['status'] == 'cancelled'
    request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/authorize", {'account': 'operativa', 'code': '123456'}, 409)
    session = checkout(client, login, order)
    with app.app_context():
        row = CheckoutSession.query.filter_by(public_id=session['id']).one()
        row.expires_at = now()-timedelta(seconds=1)
        db.session.commit()
    assert request(client, login, 'tecnico', 'get', f"/checkout/{session['id']}")['session']['status'] == 'expired'
    assert checkout(client, login, order)['id'] != session['id']


def test_checkout_permissions_private_receipt_and_demo_flags(client, login, app):
    order = fixture(client, login)
    session = checkout(client, login, order)
    request(client, login, 'empresa-b', 'get', f"/checkout/{session['id']}", status=404)
    for role in ('empresa-a', 'consulta', 'admin'):
        request(client, login, role, 'post', f"/checkout/{session['id']}/authorize", {'account': 'operativa', 'code': '123456'}, 403)
    request(client, login, 'consulta', 'post', '/payment-orders/example', {'idempotency_key': str(uuid4())}, 403)
    session = finish(client, login, app, authorize(client, login, session))
    assert client.get(f"/api/documents/{session['receipt_id']}/download", headers=login('empresa-b')).status_code == 404
    assert client.get(f"/api/documents/{session['receipt_id']}/download").status_code == 401
    with app.app_context():
        receipt_count = PaymentAttempt.query.filter_by(payment_id=order['payment_id']).count()
        assert receipt_count == 1
    old_flag = app.config['DEMO_ENVIRONMENT']
    try:
        app.config['DEMO_ENVIRONMENT'] = False
        request(client, login, 'tecnico', 'get', f"/checkout/{session['id']}", status=409)
        request(client, login, 'tecnico', 'post', '/payment-orders/example', {'idempotency_key': str(uuid4())}, 409)
    finally:
        app.config['DEMO_ENVIRONMENT'] = old_flag


def test_checkout_order_changed_and_processing_cannot_cancel(client, login, app):
    order = fixture(client, login)
    session = checkout(client, login, order)
    with app.app_context():
        payment = db.session.get(Payment, order['payment_id'])
        payment.amount = '306000.00'; payment.version += 1
        db.session.commit()
    request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/authorize", {'account': 'operativa', 'code': '123456'}, 409)
    request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/cancel")
    session = authorize(client, login, checkout(client, login, order))
    request(client, login, 'tecnico', 'post', f"/checkout/{session['id']}/cancel", status=409)
    assert request(client, login, 'tecnico', 'get', f"/checkout/{session['id']}")['session']['status'] == 'processing'
    with app.app_context():
        payment = db.session.get(Payment, order['payment_id'])
        payment.amount = '307000.00'; payment.version += 1
        db.session.commit()
    final = finish(client, login, app, session)
    assert final['status'] == 'failed' and final['result_code'] == 'order_changed'
    with app.app_context():
        assert db.session.get(Payment, order['payment_id']).status != 'pagado'


def test_checkout_concurrent_submission_and_settlement_once(client, login, app):
    order = fixture(client, login)
    session = checkout(client, login, order)
    headers = login('tecnico')
    def submit(_):
        with app.test_client() as c:
            result = c.post(f"/api/checkout/{session['id']}/authorize", headers=headers, json={'account': 'operativa', 'code': '123456'})
            return result.status_code, result.json
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(submit, range(2)))
    assert [r[0] for r in result] == [200, 200], result
    with app.app_context():
        row = CheckoutSession.query.filter_by(public_id=session['id']).one()
        row.process_after = now()-timedelta(seconds=1); db.session.commit()
    def poll(_):
        with app.test_client() as c:
            result = c.get(f"/api/checkout/{session['id']}", headers=headers)
            return result.status_code, result.json
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(poll, range(2)))
    assert [r[0] for r in results] == [200, 200], results
    assert results[0][1]['session']['receipt_id'] == results[1][1]['session']['receipt_id']
    with app.app_context():
        assert PaymentAttempt.query.filter_by(payment_id=order['payment_id']).count() == 1
        assert History.query.filter_by(work_id=order['work_id'], action='respuesta_automatica').count() == 1


def test_checkout_owner_and_scoped_order_list(client, login):
    order = fixture(client, login)
    session = checkout(client, login, order)
    request(client, login, 'admin', 'post', f"/works/{order['work_id']}/payments/{order['payment_id']}/checkout", {}, 409)
    assert order['payment_id'] not in [r['id'] for r in request(client, login, 'empresa-b', 'get', '/payment-orders')['orders']]
    assert request(client, login, 'empresa-a', 'get', f"/checkout/{session['id']}")['session']['can_authorize'] is False


def test_new_synthetic_work_can_pay_without_becoming_a_reset_fixture(client, login, app):
    order = fixture(client, login)
    with app.app_context():
        work = db.session.get(Intervention, order['work_id'])
        work.demo = False  # The ordinary create-work API preserves these on reset.
        work.code = 'OBRA-NUEVA-DEMO'
        db.session.commit()
    request(client, login, 'empresa-a', 'post', f"/works/{order['work_id']}/payments/{order['payment_id']}/checkout", {}, 403)
    # Both author and awarded company must be synthetic; a real company stays blocked.
    with app.app_context():
        work = db.session.get(Intervention, order['work_id'])
        db.session.get(Company, work.company_id).demo = False
        db.session.commit()
    checkout(client, login, order, 403)
    with app.app_context():
        work = db.session.get(Intervention, order['work_id'])
        db.session.get(Company, work.company_id).demo = True
        db.session.get(User, work.created_by).demo = False
        db.session.commit()
    request(client, login, 'admin', 'post', f"/works/{order['work_id']}/payments/{order['payment_id']}/checkout", {}, 403)
    with app.app_context():
        work = db.session.get(Intervention, order['work_id'])
        db.session.get(User, work.created_by).demo = True
        db.session.commit()
    session = checkout(client, login, order)
    authorize(client, login, session)
    assert finish(client, login, app, session)['status'] == 'succeeded'
    with app.app_context():
        assert db.session.get(Intervention, order['work_id']).demo is False
