from datetime import date, timedelta
from io import BytesIO
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from pypdf import PdfReader
from app.extensions import db
from app.models import User, ActivityLog
from app.models.domain import PaymentAttempt, CompanyRepresentative, Notification, Record
from .test_obras_flows import request, work, upload, cert_new, approve


def treasury(client, login):
    w = work(client, login, 'DEMO-MOLINO')
    c = approve(client, login, w, cert_new(client, login, w))
    p = request(client, login, 'administrativo', 'get', f"/works/{w['id']}/payments")['payments'][0]
    proof = upload(client, login, w['id'], 'admin', kind='resolucion')
    for status in ('hacienda', 'secretaria_general', 'resolucion', 'contaduria_tesoreria'):
        p = request(client, login, 'general', 'post', f"/works/{w['id']}/payments/{p['id']}/transition",
                    {'version': p['version'], 'status': status, 'comment': 'Actuación de prueba',
                     'budget_available': True, 'document_ids': [proof['id']]})['payment']
    return w, p


def test_electronic_simulator_rejection_retry_receipt_and_immutable_amount(client, login, app):
    w, p = treasury(client, login)
    url = f"/works/{w['id']}/payments/{p['id']}/attempts"
    payload = {'version': p['version'], 'idempotency_key': str(uuid4()), 'confirm_demo': True, 'amount': '0.01'}
    assert client.post('/api'+url, headers=login('empresa-a'), json=payload).status_code == 403
    result = request(client, login, 'administrativo', 'post', url, payload, 201)
    a, p = result['attempt'], result['payment']
    assert a['amount'] == p['amount'] and a['amount'] != '0.01' and a['status'] == 'pendiente'
    assert request(client, login, 'administrativo', 'post', url, payload)['attempt']['id'] == a['id']
    assert client.post('/api'+url, headers=login('administrativo'), json={**payload, 'idempotency_key': str(uuid4()), 'version': p['version']}).status_code == 409
    result = request(client, login, 'administrativo', 'post', url+f"/{a['id']}/resolve", {'status': 'rechazada', 'reason': 'Cuenta ficticia rechazada'})
    p = result['payment']
    assert p['status'] == 'contaduria_tesoreria' and result['attempt']['receipt_id'] is None
    request(client, login, 'administrativo', 'post', url+f"/{a['id']}/resolve", {'status': 'rechazada'})
    assert client.post('/api'+url+f"/{a['id']}/resolve", headers=login('administrativo'), json={'status': 'aprobada'}).status_code == 409
    result = request(client, login, 'administrativo', 'post', url, {**payload, 'version': p['version'], 'idempotency_key': str(uuid4())}, 201)
    a = result['attempt']
    result = request(client, login, 'administrativo', 'post', url+f"/{a['id']}/resolve", {'status': 'aprobada', 'reason': 'Operación ficticia aprobada'})
    p, a = result['payment'], result['attempt']
    assert p['status'] == 'pagado' and p['confirmation']['bank_transfer'] is False
    receipt = client.get(f"/api/documents/{a['receipt_id']}/download", headers=login('empresa-a'))
    content = PdfReader(BytesIO(receipt.data)).pages[0].extract_text()
    assert 'SIMULADA' in content and a['reference'] in content and p['amount'] in content
    assert client.get(f"/api/documents/{a['receipt_id']}/download", headers=login('empresa-b')).status_code == 404
    assert client.delete(f"/api/documents/{a['receipt_id']}", headers=login('admin')).status_code == 409
    assert work(client, login, 'DEMO-MOLINO')['metrics']['paid'] == p['amount']
    app.config['DEMO_ENVIRONMENT'] = False
    try:
        assert client.post('/api'+url, headers=login('administrativo'), json=payload).status_code == 409
    finally:
        app.config['DEMO_ENVIRONMENT'] = True


def test_simulator_concurrent_requests_create_one_attempt(client, login, app):
    w, p = treasury(client, login)
    path = f"/api/works/{w['id']}/payments/{p['id']}/attempts"
    headers = login('administrativo')
    def send(_):
        with app.test_client() as other:
            return other.post(path, headers=headers, json={'version': p['version'], 'confirm_demo': True, 'idempotency_key': str(uuid4())}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(send, range(2))) == [201, 409]
    with app.app_context():
        assert PaymentAttempt.query.filter_by(payment_id=p['id']).count() == 1


def test_documentary_procedure_pass_observe_remedy_approve_archive(client, login, app):
    w = work(client, login, 'DEMO-MOLINO')
    doc = upload(client, login, w['id'], name='solicitud.pdf', kind='informe')
    url = f"/works/{w['id']}/procedures"
    p = request(client, login, 'empresa-a', 'post', url, {'title': 'Revisión del plano', 'description': 'Solicitud de revisión técnica', 'due_date': str(date.today()-timedelta(days=1)), 'document_ids': [doc['id']]}, 201)['procedure']
    notices = request(client, login, 'empresa-a', 'get', '/notifications')['notifications']
    assert any(n['event_key'].startswith(f"due:procedure:{p['id']}:") for n in notices)
    def step(role, status, **extra):
        nonlocal p
        p = request(client, login, role, 'post', url+f"/{p['id']}/transition", {'version': p['version'], 'status': status, 'comment': 'Actuación documentada', **extra})['procedure']
    assert not request(client, login, 'empresa-b', 'get', '/inbox')['procedures']
    assert client.post('/api'+url+f"/{p['id']}/transition", headers=login('consulta'), json={'version': p['version'], 'status': 'ingresado', 'comment': 'No autorizado'}).status_code == 403
    step('empresa-a', 'ingresado')
    reference = request(client, login, 'admin', 'get', '/reference')
    director = next(u for u in reference['users'] if u['role'] == 'director_obra')
    step('admin', 'derivar', unit_id=director['unit_id'], responsible_id=director['id'], due_date='2026-10-13')
    step('director', 'en_revision')
    step('director', 'observado')
    step('empresa-a', 'subsanado', document_ids=[doc['id']])
    step('empresa-a', 'ingresado')
    step('director', 'en_revision')
    step('director', 'aprobado')
    step('director', 'archivado')
    assert len(p['data']['comments']) == 9 and p['responsible_id'] == director['id']
    assert not any(n['event_key'].startswith(f"due:procedure:{p['id']}:") for n in request(client, login, 'empresa-a', 'get', '/notifications')['notifications'])
    assert client.delete(f"/api/documents/{doc['id']}", headers=login('empresa-a')).status_code == 409


def test_notifications_are_persistent_private_and_due_notices_expire(client, login, app):
    w = work(client, login, 'DEMO-MOLINO')
    c = cert_new(client, login, w)
    request(client, login, 'empresa-a', 'post', f"/works/{w['id']}/certificates/{c['id']}/transition", {'version': c['version'], 'status': 'presentado'})
    notices = request(client, login, 'director', 'get', '/notifications')['notifications']
    assert notices and any(n['resource'] == 'certificado' for n in notices)
    n = notices[0]
    assert client.post(f"/api/notifications/{n['id']}/read", headers=login('empresa-b'), json={}).status_code == 404
    request(client, login, 'director', 'post', f"/notifications/{n['id']}/read")
    assert request(client, login, 'director', 'get', '/notifications')['unread'] == len(notices)-1
    first = request(client, login, 'tecnico', 'get', '/notifications')
    assert any(n['event_key'].startswith('due:record:') for n in first['notifications'])
    request(client, login, 'tecnico', 'get', '/notifications')
    with app.app_context():
        user = User.query.filter_by(email='tecnico@demo.invalid').one()
        assert Notification.query.filter_by(user_id=user.id).count() == len(first['notifications'])
        for r in Record.query.filter_by(responsible_id=user.id):
            r.status = 'finalizada'
        db.session.commit()
    assert not any(n['event_key'].startswith('due:record:') for n in request(client, login, 'tecnico', 'get', '/notifications')['notifications'])


def test_private_company_profile_document_and_representation_expiry(client, login, app):
    w = work(client, login, 'DEMO-MOLINO')
    profile = request(client, login, 'empresa-a', 'get', '/company/profile')
    cid = profile['company']['id']
    assert client.get(f"/api/companies/{cid}/profile", headers=login('empresa-b')).status_code == 404
    request(client, login, 'empresa-a', 'patch', f'/companies/{cid}/profile', {'contact': {'phone': 'DEMO-123', 'email': 'a@demo.invalid'}})
    binary = upload(client, login, w['id'])
    pdf = client.get(f"/api/documents/{binary['id']}/download", headers=login('empresa-a')).data
    result = client.post(f'/api/companies/{cid}/documents', headers=login('empresa-a'), data={'kind': 'representacion', 'file': (BytesIO(pdf), 'poder-demo.pdf')})
    assert result.status_code == 201
    doc = result.json['document']
    assert 'storage_key' not in doc
    assert client.get(f"/api/companies/{cid}/documents/{doc['id']}/download", headers=login('empresa-b')).status_code == 404
    uid = profile['representatives'][0]['user_id']
    payload = {'status': 'validada', 'start_date': str(date.today()-timedelta(days=30)), 'end_date': str(date.today()-timedelta(days=1)), 'evidence_id': doc['id']}
    request(client, login, 'admin', 'post', f'/companies/{cid}/representatives/{uid}', payload)
    assert client.get('/api/works', headers=login('empresa-a')).status_code == 403
    assert client.get('/api/company/profile', headers=login('empresa-a')).status_code == 200
    payload['end_date'] = str(date.today()+timedelta(days=30))
    request(client, login, 'admin', 'post', f'/companies/{cid}/representatives/{uid}', payload)
    assert client.get('/api/works', headers=login('empresa-a')).status_code == 200


def test_optional_coordinates_multiple_funding_historic_prices_and_denial_audit(client, login, app):
    w = request(client, login, 'tecnico', 'post', '/works', {'name': 'Ficha sin coordenadas', 'locality': 'Minas', 'latitude': None, 'longitude': None,
        'funding': [{'name': 'Origen A', 'amount': '120.50'}, {'name': 'Origen B', 'amount': '50'}]}, 201)['work']
    assert w['latitude'] is None and len(w['funding']) == 2
    w = request(client, login, 'tecnico', 'patch', f"/works/{w['id']}", {'version': w['version'], 'unit_id': None, 'description': 'Conservar fuentes'})['work']
    assert len(w['funding']) == 2 and w['unit_id'] is None
    assert client.get(f"/api/works/{w['id']}", headers=login('empresa-a')).status_code == 404
    with app.app_context():
        event = ActivityLog.query.filter_by(action='acceso_denegado').order_by(ActivityLog.id.desc()).first()
        assert event and 'work_id' in event.details and 'Authorization' not in event.details
    prices = request(client, login, 'tecnico', 'get', '/catalog/historic-prices')['prices']
    assert prices and all(p['source'] and p['date'] and p['unit'] and p['demo'] for p in prices)


def test_notification_pagination_preserves_total_unread_and_recipient_scope(client, login, app):
    w = work(client, login, 'DEMO-MOLINO')
    cert = cert_new(client, login, w)
    before = request(client, login, 'director', 'get', '/notifications')['unread']
    with app.app_context():
        user = User.query.filter_by(email='director@demo.invalid').one()
        for index in range(61):
            db.session.add(Notification(user_id=user.id, work_id=w['id'], event_key=f'pagination:{index}',
                                        resource='certificado', resource_id=cert['id'], title=f'Evento de prueba {index}'))
        db.session.commit()
    first = request(client, login, 'director', 'get', '/notifications')
    second = request(client, login, 'director', 'get', '/notifications?page=2')
    assert len(first['notifications']) == 50 and first['unread'] == before+61 and second['pages'] >= 2
    assert {n['id'] for n in first['notifications']}.isdisjoint(n['id'] for n in second['notifications'])
    notice = second['notifications'][0]
    assert client.post(f"/api/notifications/{notice['id']}/read", headers=login('empresa-b'), json={}).status_code == 404
    request(client, login, 'director', 'post', f"/notifications/{notice['id']}/read")
    assert request(client, login, 'director', 'get', '/notifications')['unread'] == before+60
