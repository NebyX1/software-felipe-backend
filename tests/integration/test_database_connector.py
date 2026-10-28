from sqlalchemy import text
from app.extensions import db


def test_real_connection_uses_mariadb_connector_python(app):
    with app.app_context():
        assert db.engine.url.drivername == 'mariadb+mariadbconnector'
        assert db.engine.dialect.driver == 'mariadbconnector'
        assert db.engine.dialect.dbapi.__name__ == 'mariadb'
        assert db.session.execute(text('SELECT DATABASE()')).scalar() == 'obras_test'
        assert 'MariaDB' in db.session.execute(text('SELECT VERSION()')).scalar()


def test_read_committed_and_pool_settings_survive_the_driver_change(app):
    with app.app_context():
        assert db.session.execute(text('SELECT @@tx_isolation')).scalar() == 'READ-COMMITTED'
        options = app.config['SQLALCHEMY_ENGINE_OPTIONS']
        assert db.engine.pool.size() == options['pool_size']
        assert db.engine.pool.timeout() == options['pool_timeout']
        assert db.engine.pool._recycle == options['pool_recycle']


def test_schema_migrations_can_start_with_only_the_database(app, monkeypatch):
    from bootstrap import initialize
    def unexpected_storage():
        raise AssertionError('Database-only startup must not initialize object storage.')
    monkeypatch.setattr('bootstrap.get_document_storage', unexpected_storage)
    initialize(app, seed_demo=False, initialize_storage=False)
