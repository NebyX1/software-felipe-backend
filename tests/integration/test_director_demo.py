from uuid import uuid4
from sqlalchemy import text
from app.extensions import db
from app.models import User
from app.models.domain import DemoInstallation, Intervention, Document, AuthSession
import bootstrap


def clear_test_database(app):
    with app.app_context():
        assert db.engine.url.database == 'obras_test'
        db.session.execute(text('SET FOREIGN_KEY_CHECKS=0'))
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.execute(text('SET FOREIGN_KEY_CHECKS=1'))
        db.session.commit()


def test_private_invitation_required_and_never_returned(client, app, monkeypatch):
    private_code = str(uuid4())
    monkeypatch.setitem(app.config, 'DEMO_ACCESS_CODE', private_code)
    accounts = client.get('/api/auth/accounts')
    assert accounts.json['access_required'] is True
    assert private_code not in accounts.get_data(as_text=True)
    for code in ('', 'wrong', None, [], {'value': private_code}):
        response = client.post('/api/auth/login', json={'account': 'general@demo.invalid', 'access_code': code})
        assert response.status_code == 403 and response.json['code'] == 'demo_access_denied'
        assert private_code not in response.get_data(as_text=True)
    with app.app_context():
        assert AuthSession.query.count() == 0
    response = client.post('/api/auth/login', json={'account': 'general@demo.invalid', 'access_code': private_code})
    assert response.status_code == 200 and response.json['user']['role'] == 'direccion_general'
    assert private_code not in response.get_data(as_text=True)


def test_invalid_login_payload_returns_validation_error(client):
    for payload in (['general@demo.invalid'], {'account': []}, {'account': None}):
        assert client.post('/api/auth/login', json=payload).status_code == 422


def test_guide_metadata_respects_company_scope_and_ai_disabled(client, login, monkeypatch):
    monkeypatch.setenv('AI_ENABLED', 'false')
    headers = login('empresa-b')
    result = client.get('/api/demo/scenarios', headers=headers)
    assert result.json['assistant_available'] is False
    assert result.json['works'] and all(row['code'] not in ('DEMO-MOLINO', 'DEMO-POSOBRA') for row in result.json['works'])


def test_practice_files_are_authenticated_and_importable(client, login):
    from app.services.importing import preview
    assert client.get('/api/demo/materials/rubrado.xlsx').status_code == 401
    headers = login('general')
    response = client.get('/api/demo/materials/rubrado.xlsx', headers=headers)
    assert response.status_code == 200
    result = preview(response.data, 'rubrado-demo.xlsx', 'rubrado')
    assert not result['errors'] and len(result['rows']) == 2
    response = client.get('/api/demo/materials/factura.pdf', headers=headers)
    assert response.status_code == 200 and response.data.startswith(b'%PDF')
    assert client.get('/api/demo/materials/secret.env', headers=headers).status_code == 404


def test_existing_installation_only_migrates_without_reseeding(client, app):
    with app.app_context():
        work = Intervention.query.filter_by(code='DEMO-MOLINO').one()
        work.description = 'Cambio conservado de la evaluación'
        db.session.commit()
        counts = (Intervention.query.count(), Document.query.count())
    bootstrap.initialize(app)
    bootstrap.initialize(app)
    with app.app_context():
        assert DemoInstallation.query.one().state == 'ready'
        assert (Intervention.query.count(), Document.query.count()) == counts
        assert Intervention.query.filter_by(code='DEMO-MOLINO').one().description == 'Cambio conservado de la evaluación'


def test_fresh_installation_initializes_once_and_recovers_interrupted_seed(client, app, monkeypatch):
    clear_test_database(app)
    real_seed = bootstrap.seed
    def interrupted():
        raise RuntimeError('Synthetic interruption')
    monkeypatch.setattr(bootstrap, 'seed', interrupted)
    import pytest
    with pytest.raises(RuntimeError, match='Synthetic interruption'):
        bootstrap.initialize(app)
    with app.app_context():
        assert DemoInstallation.query.one().state == 'initializing'
        assert db.session.execute(text('SELECT IS_FREE_LOCK(:name)'), {'name': 'obras_test:bootstrap'}).scalar() == 1
    monkeypatch.setattr(bootstrap, 'seed', real_seed)
    bootstrap.initialize(app)
    with app.app_context():
        assert User.query.filter_by(demo=True).count() == 9
        assert Intervention.query.count() == 5
        assert Document.query.count() > 0
        assert DemoInstallation.query.one().state == 'ready'
        counts = (Intervention.query.count(), Document.query.count())
    bootstrap.initialize(app)
    with app.app_context():
        assert (Intervention.query.count(), Document.query.count()) == counts
