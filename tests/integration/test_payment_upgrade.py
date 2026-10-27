"""Old browser tabs get an actionable upgrade message, never a retired action."""
from app.extensions import db
from app.models.domain import CheckoutSession, PaymentAttempt, Payment
from .test_obras_flows import request


def test_retired_payment_screen_requests_refresh_without_modifying_data(client, login, app):
    with app.app_context():
        before = (Payment.query.count(), PaymentAttempt.query.count(), CheckoutSession.query.count())
    for method, path in (
        ('get', '/demo/payment-runs'),
        ('post', '/demo/payment-runs'),
        ('get', '/demo/payment-runs/3'),
        ('post', '/demo/payment-runs/3/advance'),
    ):
        result = request(client, login, 'tecnico', method, path,
                         {'step': 'responder', 'result': 'aprobada'}, 410)
        assert result['code'] == 'client_outdated'
        assert result['reload_url'] == '/pagos'
        assert 'Ctrl + F5' in result['message']
        assert 'not found' not in result['message']
    with app.app_context():
        assert before == (Payment.query.count(), PaymentAttempt.query.count(), CheckoutSession.query.count())
    assert request(client, login, 'tecnico', 'get', '/payment-orders')['can_create_example'] is True
    assert client.get('/api/demo/payment-runs').status_code == 401
