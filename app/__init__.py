"""CivicFlow application factory, extended for the Lavalleja works domain."""
import os
from pathlib import Path
from uuid import uuid4
from flask import Flask, jsonify, request, g
from flask_cors import CORS
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError,OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException
from .config import Config
from .extensions import db, migrate, mail, jwt, limiter, login_manager, csrf


def create_app(test_config=None):
    app = Flask(__name__, static_folder='../public', static_url_path='/static')
    app.config.from_object(Config)
    app.config.update(
        DEMO_AUTH_ENABLED=os.getenv('DEMO_AUTH_ENABLED', 'false').lower() == 'true',
        DEMO_ENVIRONMENT=os.getenv('DEMO_ENVIRONMENT', 'false').lower() == 'true',
        DEMO_ACCESS_CODE=os.getenv('DEMO_ACCESS_CODE', ''),
        DOCUMENT_STORAGE=os.getenv('DOCUMENT_STORAGE', 'minio'),
        DOCUMENT_ROOT=os.getenv('DOCUMENT_ROOT', str(Path(__file__).resolve().parents[2] / 'private-data')),
        MINIO_ENDPOINT=os.getenv('MINIO_ENDPOINT', '127.0.0.1:39000'),
        MINIO_ACCESS_KEY=os.getenv('MINIO_ACCESS_KEY'), MINIO_SECRET_KEY=os.getenv('MINIO_SECRET_KEY'),
        MINIO_BUCKET_NAME=os.getenv('MINIO_BUCKET_NAME', 'lavalleja-obras'),
        MINIO_SECURE=os.getenv('MINIO_SECURE', 'false').lower() == 'true',
        MAX_CONTENT_LENGTH=21 * 1024 * 1024,
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
        MAINTENANCE_MODE=os.getenv('MAINTENANCE_MODE', 'false').lower() == 'true',
    )
    if test_config:
        app.config.update(test_config)
    if not app.testing and os.getenv('DEMO_ACCESS_REQUIRED', 'false').lower() == 'true' and len(app.config['DEMO_ACCESS_CODE']) < 8:
        raise RuntimeError('Configure un código privado de demo de al menos 8 caracteres.')
    if not app.testing and app.config['SECRET_KEY'] == 'change-me-in-production-please':
        raise RuntimeError('Configure SECRET_KEY in backend/.env before starting the application.')
    if not app.testing and not app.config['SQLALCHEMY_DATABASE_URI'].startswith(('mysql','mariadb')):
        raise RuntimeError('DATABASE_URL must point to MariaDB for this deployment.')
    if not app.testing and app.config['DOCUMENT_STORAGE']!='minio':
        raise RuntimeError('Deployment requires private MinIO/S3 document storage.')
    if os.getenv('TRUST_PROXY', 'false').lower() == 'true':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    CORS(app, origins=app.config['CORS_ALLOWED_ORIGINS'], supports_credentials=True)
    for extension in (db, mail, jwt, limiter, login_manager, csrf):
        extension.init_app(app)
    migrate.init_app(app, db, directory=str(Path(__file__).resolve().parents[1] / 'migrations'))
    from . import models
    from .models.domain import AuthSession
    from .services.errors import DomainError

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(models.User, int(user_id))
        return user if user and user.is_active and (not user.demo or app.config['DEMO_AUTH_ENABLED']) else None

    @jwt.token_in_blocklist_loader
    def revoked(_header, payload):
        session = AuthSession.query.filter_by(jti=payload['jti']).first()
        return session is None or session.revoked

    @jwt.unauthorized_loader
    @jwt.invalid_token_loader
    def jwt_error(_reason):
        return jsonify(code='unauthorized', message='Iniciá sesión para continuar.'), 401

    @jwt.expired_token_loader
    @jwt.revoked_token_loader
    def invalid_jwt(_header, _payload):
        return jsonify(code='unauthorized', message='La sesión expiró o fue cerrada.'), 401

    @app.before_request
    def context():
        g.request_id = uuid4().hex
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and app.config['MAINTENANCE_MODE']:
            raise DomainError('El sistema está en mantenimiento para respaldo.', 503)

    @app.after_request
    def headers(response):
        response.headers['X-Request-ID'] = g.get('request_id', '')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(DomainError)
    def domain_error(error):
        db.session.rollback()
        if error.status == 403 or (error.status == 404 and g.get('user')):
            import json
            actor = g.get('user')
            db.session.add(models.ActivityLog(user_id=actor.id if actor else None, action='acceso_denegado',
                details=json.dumps({'request_id': g.get('request_id'), 'route': request.url_rule.rule if request.url_rule else None,
                                    'method': request.method, 'resources': {k: v for k, v in (request.view_args or {}).items() if k.endswith('_id')},
                                    'code': error.code})))
            db.session.commit()
        return jsonify(code=error.code, message=error.message, fields=error.fields, request_id=g.get('request_id')), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        db.session.rollback()
        return jsonify(code='http_error', message=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        db.session.rollback()
        app.logger.error('Request failed id=%s type=%s', g.get('request_id'), type(error).__name__)
        if app.testing:
            raise error
        return jsonify(code='internal_error', message='No se pudo completar la operación. El registro previo se conserva.'), 500

    @app.errorhandler(IntegrityError)
    def integrity_error(error):
        db.session.rollback()
        return jsonify(code='data_conflict',message='El registro ya existe o sus referencias cambiaron. Recargá antes de reintentar.'),409

    @app.errorhandler(OperationalError)
    def database_error(error):
        db.session.rollback()
        number=error.orig.args[0] if getattr(error,'orig',None) and error.orig.args else None
        if number in (1205,1213):return jsonify(code='concurrent_operation',message='Otra operación está modificando el recurso. Recargá y reintentá.'),409
        app.logger.error('Database unavailable id=%s',g.get('request_id'))
        return jsonify(code='database_unavailable',message='Base de datos no disponible.'),503

    @app.get('/health')
    @app.get('/api/health/live')
    def live():
        return {'status': 'ok', 'service': 'lavalleja-obras', 'demo': app.config['DEMO_AUTH_ENABLED']}

    @app.get('/api/health/ready')
    def ready():
        from .infrastructure.storage import get_document_storage
        try:
            db.session.execute(text('SELECT 1'))
            storage_ok = get_document_storage().healthy()
            redis_ok = True
            if app.config['REDIS_URL'].startswith('redis'):
                import redis
                redis_ok = redis.Redis.from_url(app.config['REDIS_URL'], socket_timeout=2).ping()
            return {'database': True, 'storage': storage_ok, 'redis': redis_ok}, 200 if storage_ok and redis_ok else 503
        except Exception:
            return {'status': 'unavailable'}, 503

    from .api import api_bp
    app.register_blueprint(api_bp)
    csrf.exempt(api_bp)
    from .admin_demo import admin_bp
    app.register_blueprint(admin_bp)
    from .demo import seed_demo, reset_demo, init_bucket
    for command in (seed_demo, reset_demo, init_bucket):
        app.cli.add_command(command)
    return app
