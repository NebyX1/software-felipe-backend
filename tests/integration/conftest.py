"""MariaDB/MinIO integration; never touches obras_demo or supplied documents."""
import os
from pathlib import Path
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from flask_migrate import upgrade
from app import create_app
from app.extensions import db
from app.demo import seed
from app.infrastructure.storage import get_document_storage

@pytest.fixture(scope='session')
def app():
    from app.config import Config
    test_url = os.getenv('TEST_DATABASE_URL') or make_url(Config.SQLALCHEMY_DATABASE_URI).set(database='obras_test').render_as_string(hide_password=False)
    application=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':test_url,'MINIO_BUCKET_NAME':'lavalleja-obras-test','RATELIMIT_ENABLED':False,'DEMO_AUTH_ENABLED':True,'DEMO_ENVIRONMENT':True,'DEMO_ACCESS_CODE':''})
    with application.app_context():
        assert db.engine.url.database=='obras_test','Tests destructive only in obras_test'
        upgrade(directory=str(Path(__file__).resolve().parents[2]/'migrations'))
        storage=get_document_storage()
        if not storage.client.bucket_exists(storage.bucket):storage.client.make_bucket(storage.bucket)
    return application

@pytest.fixture()
def client(app):
    with app.app_context():
        # Dedicated schema, verified above. Clear all business tables between cases.
        db.session.execute(text('SET FOREIGN_KEY_CHECKS=0'))
        for table in reversed(db.metadata.sorted_tables):db.session.execute(table.delete())
        db.session.execute(text('SET FOREIGN_KEY_CHECKS=1'));db.session.commit();seed(with_certificates=False)
    return app.test_client()

@pytest.fixture()
def login(client):
    cache={}
    def account(name):
        if name not in cache:
            result=client.post('/api/auth/login',json={'account':name+'@demo.invalid'})
            assert result.status_code==200,result.json
            cache[name]={'Authorization':'Bearer '+result.json['token']}
        return cache[name]
    return account
