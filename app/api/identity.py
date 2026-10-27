from flask import current_app, request, g
from hmac import compare_digest
from flask_jwt_extended import create_access_token, decode_token, get_jwt
from flask_login import login_user, logout_user
from ..extensions import db, limiter
from ..models import User, ActivityLog
from ..models.domain import AuthSession
from ..services.access import authenticated
from ..services.errors import require
from . import api_bp


class DemoIdentityProvider:
    """Replaceable provider. Server-selected demo accounts are the entire surface."""
    def authenticate(self, account):
        require(current_app.config['DEMO_AUTH_ENABLED'], 'El proveedor demo está deshabilitado.', 403, 'demo_disabled')
        user = User.query.filter_by(email=account, demo=True, is_active=True).first()
        require(user, 'Cuenta demo inválida.', 401)
        return user


@api_bp.get('/auth/accounts')
def accounts():
    require(current_app.config['DEMO_AUTH_ENABLED'], 'Login demo deshabilitado.', 404)
    return {'accounts': [u.to_dict() for u in User.query.filter_by(demo=True, is_active=True).order_by(User.id)],
            'access_required': bool(current_app.config.get('DEMO_ACCESS_CODE'))}


@api_bp.post('/auth/login')
@limiter.limit(lambda:current_app.config.get('DEMO_LOGIN_RATE_LIMIT','120/minute'))
def login():
    payload = request.get_json(silent=True) or {}
    require(isinstance(payload, dict), 'Solicitud de ingreso inválida.')
    expected = current_app.config.get('DEMO_ACCESS_CODE', '')
    supplied = payload.get('access_code', '')
    if expected:
        require(isinstance(supplied, str) and compare_digest(expected.encode(), supplied.encode()),
                'El código de acceso a la demo no es correcto.', 403, 'demo_access_denied')
    require(isinstance(payload.get('account'), str) and len(payload['account']) <= 254,
            'Seleccioná una cuenta de prueba válida.')
    user = DemoIdentityProvider().authenticate(payload.get('account', ''))
    token = create_access_token(identity=str(user.id))
    db.session.add(AuthSession(user_id=user.id, jti=decode_token(token)['jti']))
    db.session.add(ActivityLog(user_id=user.id, action='demo:login'))
    login_user(user)
    db.session.commit()
    return {'token': token, 'user': user.to_dict(), 'provider': 'demo'}


@api_bp.get('/auth/me')
@authenticated
def me():
    return {'user': g.user.to_dict(), 'provider': 'demo' if g.user.demo else 'institutional'}


@api_bp.post('/auth/logout')
@authenticated
def logout():
    session = AuthSession.query.filter_by(jti=get_jwt()['jti']).first()
    if session:
        session.revoked = True
    db.session.add(ActivityLog(user_id=g.user.id, action='logout'))
    logout_user()
    db.session.commit()
    return {'ok': True}
