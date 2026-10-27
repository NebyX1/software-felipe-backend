"""Supplier demo presenters can pay fixtures without acquiring treasury permissions."""
from datetime import timedelta
from io import BytesIO
from uuid import uuid4
import pytest
from pypdf import PdfReader
from app.extensions import db
from app.models import User
from app.models.domain import Certificate, CheckoutSession, Company, Intervention, Payment, PaymentAttempt, now
from .test_obras_flows import request


def example(client, login, role):
    payload = {'idempotency_key': str(uuid4()), 'company_id': -1}
    order = request(client, login, role, 'post', '/payment-orders/example', payload, 201)
    assert request(client, login, role, 'post', '/payment-orders/example', payload) == order
    return order


def path(order):
    return f"/works/{order['work_id']}/payments/{order['payment_id']}/checkout"


def finish(client, login, app, role, session):
    with app.app_context():
        row = CheckoutSession.query.filter_by(public_id=session['id']).one()
        row.process_after = now()-timedelta(seconds=1)
        db.session.commit()
    return request(client, login, role, 'get', f"/checkout/{session['id']}")['session']


@pytest.mark.parametrize('letter', ['a', 'b'])
def test_supplier_can_complete_own_fixture_rejection_retry_and_receipt(client, login, app, letter):
    role = 'empresa-'+letter
    other = 'empresa-'+('b' if letter == 'a' else 'a')
    order = example(client, login, role)
    rows = request(client, login, role, 'get', '/payment-orders')
    assert rows['view'] == 'supplier' and rows['can_create_example']
    row = next(r for r in rows['orders'] if r['id'] == order['payment_id'])
    assert row['can_pay'] and row['is_example'] and row['presentation_mode']
    assert row['company_name'] == 'Empresa Demo '+letter.upper()
    session = request(client, login, role, 'post', path(order), {}, 201)['session']
    assert session['can_authorize'] and session['presentation_mode']
    assert request(client, login, role, 'post', path(order))['session']['id'] == session['id']
    request(client, login, other, 'get', f"/checkout/{session['id']}", status=404)
    request(client, login, other, 'post', path(order), {}, 404)
    session = request(client, login, role, 'post', f"/checkout/{session['id']}/authorize",
                      {'account': 'sin_saldo', 'code': '123456', 'result': 'aprobada', 'amount': '1.00'})['session']
    assert session['status'] == 'processing' and session['amount'] == '305000.00'
    session = finish(client, login, app, role, session)
    assert session['status'] == 'failed' and not session['receipt_id']
    session = request(client, login, role, 'post', path(order), {}, 201)['session']
    session = request(client, login, role, 'post', f"/checkout/{session['id']}/authorize", {'account': 'operativa', 'code': '123456'})['session']
    session = finish(client, login, app, role, session)
    assert session['status'] == 'succeeded' and session['receipt_id']
    assert request(client, login, role, 'get', f"/checkout/{session['id']}")['session']['receipt_id'] == session['receipt_id']
    receipt = client.get(f"/api/documents/{session['receipt_id']}/download", headers=login(role))
    assert receipt.status_code == 200
    pdf = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(receipt.data)).pages)
    assert 'SIMULADA' in pdf and 'Empresa Demo '+letter.upper() in pdf and '305000.00' in pdf
    assert client.get(f"/api/documents/{session['receipt_id']}/download", headers=login(other)).status_code == 404
    paid = next(r for r in request(client, login, role, 'get', '/payment-orders')['orders'] if r['id'] == order['payment_id'])
    assert paid['status'] == 'paid' and not paid['can_pay']
    with app.app_context():
        user = User.query.filter_by(email=role+'@demo.invalid').one()
        assert user.role == 'empresa'
        attempts = PaymentAttempt.query.filter_by(payment_id=order['payment_id']).order_by(PaymentAttempt.id).all()
        assert [a.status for a in attempts] == ['rechazada', 'aprobada']
        assert all(a.actor_id == user.id for a in attempts)
        assert db.session.get(Intervention, order['work_id']).company_id == user.company_id


def test_supplier_can_pay_existing_fixture_but_not_ordinary_order(client, login, app):
    order = example(client, login, 'tecnico')
    assert next(r for r in request(client, login, 'empresa-a', 'get', '/payment-orders')['orders'] if r['id'] == order['payment_id'])['can_pay']
    session = request(client, login, 'empresa-a', 'post', path(order), {}, 201)['session']
    assert session['can_authorize']
    request(client, login, 'empresa-a', 'post', f"/checkout/{session['id']}/cancel")
    with app.app_context():
        payment = db.session.get(Payment, order['payment_id'])
        cert = db.session.get(Certificate, payment.certificate_id)
        cert.approved_snapshot = {**cert.approved_snapshot, 'fixture': False}
        db.session.commit()
    ordinary = next(r for r in request(client, login, 'empresa-a', 'get', '/payment-orders')['orders'] if r['id'] == order['payment_id'])
    assert not ordinary['can_pay'] and not ordinary['is_example']
    assert ordinary['unavailable_reason'] == 'Este pago lo realiza Tesorería.'
    request(client, login, 'empresa-a', 'post', path(order), {}, 403)
    request(client, login, 'consulta', 'post', '/payment-orders/example', {'idempotency_key': str(uuid4())}, 403)
    with app.app_context():
        assert db.session.get(Payment, order['payment_id']).status == 'contaduria_tesoreria'
        assert PaymentAttempt.query.filter_by(payment_id=order['payment_id']).count() == 0


def test_supplier_cannot_take_over_another_users_active_session(client, login):
    order = example(client, login, 'tecnico')
    session = request(client, login, 'tecnico', 'post', path(order), {}, 201)['session']
    row = next(r for r in request(client, login, 'empresa-a', 'get', '/payment-orders')['orders'] if r['id'] == order['payment_id'])
    assert not row['can_pay'] and not row['can_resume'] and 'Otra persona' in row['unavailable_reason']
    request(client, login, 'empresa-a', 'post', path(order), {}, 409)
    request(client, login, 'empresa-a', 'post', f"/checkout/{session['id']}/authorize", {'account': 'operativa', 'code': '123456'}, 403)
    own = example(client, login, 'empresa-a')
    assert request(client, login, 'empresa-a', 'post', path(own), {}, 201)['session']['can_authorize']


def test_supplier_sandbox_requires_synthetic_identity_company_and_demo_flags(client, login, app, monkeypatch):
    order = example(client, login, 'empresa-a')
    monkeypatch.setitem(app.config, 'DEMO_ENVIRONMENT', False)
    request(client, login, 'empresa-a', 'post', path(order), {}, 409)
    monkeypatch.setitem(app.config, 'DEMO_ENVIRONMENT', True)
    with app.app_context():
        user = User.query.filter_by(email='empresa-a@demo.invalid').one()
        company = db.session.get(Company, user.company_id)
        company.demo = False
        db.session.commit()
    request(client, login, 'empresa-a', 'post', path(order), {}, 403)
    rows = request(client, login, 'empresa-a', 'get', '/payment-orders')
    assert not rows['can_create_example'] and not any(r['can_pay'] for r in rows['orders'])
    with app.app_context():
        user = User.query.filter_by(email='empresa-a@demo.invalid').one()
        db.session.get(Company, user.company_id).demo = True
        user.demo = False
        db.session.commit()
    request(client, login, 'empresa-a', 'post', path(order), {}, 409)
    with app.app_context():
        User.query.filter_by(email='empresa-a@demo.invalid').one().demo = True
        db.session.commit()
    monkeypatch.setitem(app.config, 'DEMO_AUTH_ENABLED', False)
    request(client, login, 'empresa-a', 'post', path(order), {}, 401)
