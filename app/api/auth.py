"""
Authentication endpoints:
  POST /api/auth/login        – step 1: email + password
  POST /api/auth/verify-2fa   – step 2: 6-digit code
  GET  /api/auth/me           – current user info
  POST /api/auth/logout       – logout (client-side token discard)
  PUT  /api/auth/change-password – change own password
"""
from datetime import datetime, timezone

from flask import request, current_app
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
    get_jwt,
)

from . import api_bp, auth_public_bp
from ..extensions import db
from ..models import User, TwoFactorCode, ActivityLog
from ..services.email_service import send_2fa_email

# ─── helpers ──────────────────────────────────────────────────────────────────


def _log(action: str, user_id=None, entity_type=None, entity_id=None, details=None):
    import json as _json
    detail_str = None
    if details or entity_type:
        d = {}
        if entity_type:
            d['entity_type'] = entity_type
        if entity_id is not None:
            d['entity_id'] = entity_id
        if details:
            d.update(details)
        detail_str = _json.dumps(d, ensure_ascii=False)
    log = ActivityLog(
        user_id=user_id,
        action=action,
        details=detail_str,
        ip_address=request.remote_addr,
    )
    db.session.add(log)


def _bad(msg: str, code: int = 400):
    return {"error": msg}, code


def _ok(data: dict, code: int = 200):
    return data, code


# ─── routes ───────────────────────────────────────────────────────────────────


@auth_public_bp.route('/auth/login', methods=['POST'], strict_slashes=False)
@api_bp.route('/auth/login', methods=['POST'], strict_slashes=False)
def login():
    """Step 1 – validate credentials, send 2FA code."""
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return _bad("Email y contraseña son requeridos.")

    user: User | None = User.query.filter_by(email=email, is_active=True).first()
    if not user or not user.check_password(password):
        return _bad("Credenciales incorrectas.", 401)

    # Invalidate previous unused codes
    TwoFactorCode.query.filter_by(user_id=user.id).filter(
        TwoFactorCode.consumed_at.is_(None)
    ).delete(synchronize_session=False)

    code_entry = TwoFactorCode.generate(user)
    db.session.commit()

    try:
        send_2fa_email(user.email, user.name, code_entry.code, current_app._get_current_object())
    except Exception as exc:
        current_app.logger.error(f"2FA email failed for {email}: {exc}")
        # Don't reveal email errors to client

    # Short-lived "pending" token used in step 2
    pending_token = create_access_token(
        identity=str(user.id),
        additional_claims={"type": "2fa_pending"},
        expires_delta=__import__("datetime").timedelta(minutes=10),
    )

    _log("login_step1", user.id, "user", user.id, {"email": email})
    db.session.commit()

    return _ok({"requires_2fa": True, "pending_token": pending_token})


@auth_public_bp.route(
    '/auth/verify-2fa', methods=['POST'], strict_slashes=False
)
@api_bp.route('/auth/verify-2fa', methods=['POST'], strict_slashes=False)
@jwt_required()
def verify_2fa():
    """Step 2 – verify 2FA code, issue full access token."""
    claims = get_jwt()
    if claims.get("type") != "2fa_pending":
        return _bad("Token inválido para este endpoint.", 403)

    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    submitted_code = (body.get("code") or "").strip()

    if not submitted_code:
        return _bad("El código es requerido.")

    code_entry: TwoFactorCode | None = (
        TwoFactorCode.query
        .filter_by(user_id=user_id)
        .filter(TwoFactorCode.consumed_at.is_(None))
        .order_by(TwoFactorCode.id.desc())
        .first()
    )

    if not code_entry or not code_entry.is_valid(submitted_code):
        return _bad("Código inválido o expirado.", 401)

    code_entry.used = True

    user: User = User.query.get(user_id)
    user.last_login = datetime.now(timezone.utc)

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={
            "type": "access",
            "role": user.role,
            "unit_id": user.unit_id,
        },
    )

    _log("login_success", user.id, "user", user.id)
    db.session.commit()

    return _ok({"access_token": access_token, "user": user.to_dict()})


@auth_public_bp.route('/auth/me', methods=['GET'], strict_slashes=False)
@api_bp.route('/auth/me', methods=['GET'], strict_slashes=False)
@jwt_required()
def me():
    """Return the authenticated user's profile."""
    claims = get_jwt()
    if claims.get("type") != "access":
        return _bad("Token inválido.", 403)
    user: User = User.query.get(int(get_jwt_identity()))
    if not user or not user.is_active:
        return _bad("Usuario no encontrado.", 404)
    return _ok({"user": user.to_dict()})


@auth_public_bp.route('/auth/logout', methods=['POST'], strict_slashes=False)
@api_bp.route('/auth/logout', methods=['POST'], strict_slashes=False)
@jwt_required()
def logout():
    """Client discards token; we just log it."""
    claims = get_jwt()
    if claims.get("type") == "access":
        user_id = int(get_jwt_identity())
        _log("logout", user_id, "user", user_id)
        db.session.commit()
    return _ok({"message": "Sesión cerrada."})


@auth_public_bp.route(
    '/auth/change-password', methods=['PUT'], strict_slashes=False
)
@api_bp.route('/auth/change-password', methods=['PUT'], strict_slashes=False)
@jwt_required()
def change_password():
    """Allow any authenticated user to change their own password."""
    claims = get_jwt()
    if claims.get("type") != "access":
        return _bad("Token inválido.", 403)

    user: User = User.query.get(int(get_jwt_identity()))
    if not user or not user.is_active:
        return _bad("Usuario no encontrado.", 404)

    body = request.get_json(silent=True) or {}
    current_pw = body.get("current_password") or ""
    new_pw = body.get("new_password") or ""

    if not current_pw or not new_pw:
        return _bad("Se requiere la contraseña actual y la nueva.")
    if len(new_pw) < 8:
        return _bad("La nueva contraseña debe tener al menos 8 caracteres.")
    if not user.check_password(current_pw):
        return _bad("La contraseña actual es incorrecta.", 401)

    user.set_password(new_pw)
    _log("change_password", user.id, "user", user.id)
    db.session.commit()

    return _ok({"message": "Contraseña actualizada correctamente."})
