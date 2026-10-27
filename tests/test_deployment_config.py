from sqlalchemy.engine import make_url
from app.config import database_uri


def test_separate_database_credentials_escape_symbols_without_changing_password():
    password = 'synthetic:@/#?$&%+space test'
    uri = make_url(database_uri({'DATABASE_HOST': 'db', 'DATABASE_PASSWORD': password}))
    assert uri.password == password
    assert uri.host == 'db' and uri.database == 'obras_demo' and uri.username == 'obras'


def test_existing_database_url_remains_supported():
    assert database_uri({'DATABASE_URL': 'mysql+pymysql://demo:fake@localhost/db'}) == 'mysql+pymysql://demo:fake@localhost/db'
