import pytest
from sqlalchemy.engine import make_url
from app import create_app
from app.config import database_uri, validate_database_uri

URL = 'mariadb+mariadbconnector://root:synthetic%40%2F%23%2B@localhost:3306/software_felipe'


def test_database_url_is_preserved_and_takes_precedence_over_legacy_fragments():
    values = {'DATABASE_URL': URL, 'SQLALCHEMY_DATABASE_URI': 'ignored',
              'DATABASE_HOST': 'wrong-server', 'DATABASE_PASSWORD': 'ignored'}
    assert database_uri(values) == URL
    assert validate_database_uri(URL) == URL
    assert make_url(URL).password == 'synthetic@/#+'


def test_sqlalchemy_alias_matches_buzon_reference():
    assert database_uri({'SQLALCHEMY_DATABASE_URI': URL}) == URL


def test_missing_url_does_not_invent_a_database_or_driver():
    assert database_uri({}) is None
    assert database_uri({'DATABASE_HOST': 'db', 'DATABASE_URI': URL}) is None


@pytest.mark.parametrize('value', [None, '', 'sqlite:///local.db',
    'mysql+pymysql://root:synthetic-private-password@localhost/db',
    'mariadb+mariadbconnector://root:synthetic-private-password@localhost',
    'mariadb+mariadbconnector://root:synthetic-private-password@localhost:invalid/db'])
def test_invalid_connection_fails_without_exposing_credentials(value):
    with pytest.raises(ValueError, match='DATABASE_URL') as error:
        validate_database_uri(value)
    assert 'synthetic-private-password' not in str(error.value)


@pytest.mark.parametrize('profile,debug,secure', [
    ('default', True, False), ('development', True, False),
    ('production', False, True), ('testing', False, False),
])
def test_factory_uses_institutional_profiles(monkeypatch, profile, debug, secure):
    monkeypatch.delenv('COOKIE_SECURE', raising=False)
    app = create_app(profile, test_config={'SECRET_KEY': 'synthetic-unit-secret',
        'SQLALCHEMY_DATABASE_URI': URL, 'DEMO_ACCESS_CODE': 'synthetic-unit-code'})
    assert app.debug is debug
    assert app.config['SESSION_COOKIE_SECURE'] is secure
    assert app.config['SQLALCHEMY_DATABASE_URI'] == URL
    assert app.testing is (profile == 'testing')


def test_factory_rejects_invalid_profile():
    with pytest.raises(ValueError, match='FLASK_CONFIG'):
        create_app('invalid-profile')
