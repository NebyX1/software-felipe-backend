"""
User management endpoints (admin+ only, except profile/password).
  GET  /api/users              – list users (admin+)
  POST /api/users              – create user (admin+)
  GET  /api/users/<id>         – user detail (admin+ or self)
  PUT  /api/users/<id>         – update user (admin+ or self for limited fields)
  DELETE /api/users/<id>       – deactivate user (admin+)
  PUT  /api/users/<id>/reset-password  – admin resets password for a user
"""
import secrets
import string
from flask import request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from . import api_bp
from ..extensions import db
from ..models import User, ActivityLog
from ..services.email_service import send_welcome_email


def _require_admin(claims):
    return claims.get("role") in ("admin", "super_admin")


def _log(action, user_id, entity_id=None, details=None):
    import json as _json
    detail_str = None
    if details or entity_id is not None:
        d = {"entity_type": "user"}
        if entity_id is not None:
            d["entity_id"] = entity_id
        if details:
            d.update(details)
        detail_str = _json.dumps(d, ensure_ascii=False)
    db.session.add(ActivityLog(
        user_id=user_id, action=action,
        details=detail_str, ip_address=request.remote_addr,
    ))


@api_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    unit_id = request.args.get("unit_id", type=int)
    role = request.args.get("role")
    q = User.query.order_by(User.name)
    if unit_id:
        q = q.filter_by(unit_id=unit_id)
    if role:
        q = q.filter_by(role=role)

    return {"users": [u.to_dict() for u in q.all()]}, 200


@api_bp.route("/users", methods=["POST"])
@jwt_required()
def create_user():
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    role = body.get("role") or "user"
    unit_id = body.get("unit_id")
    password = body.get("password") or ""

    if not name or not email or not password:
        return {"error": "Nombre, email y contraseña son requeridos."}, 400
    if role not in ("super_admin", "admin", "user"):
        return {"error": "Rol inválido."}, 400
    if role == "user" and not unit_id:
        return {"error": "Los usuarios deben pertenecer a una unidad."}, 400
    if len(password) < 8:
        return {"error": "La contraseña debe tener al menos 8 caracteres."}, 400

    # Only super_admin can create admins/super_admins
    if role in ("admin", "super_admin") and claims.get("role") != "super_admin":
        return {"error": "Solo el super administrador puede crear administradores."}, 403

    if User.query.filter_by(email=email).first():
        return {"error": "Ya existe un usuario con ese email."}, 409

    user = User(name=name, email=email, role=role, unit_id=unit_id or None)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    _log("create_user", int(get_jwt_identity()), user.id, {"email": email, "role": role})
    db.session.commit()

    return {"user": user.to_dict()}, 201


@api_bp.route("/users/<int:uid>", methods=["GET"])
@jwt_required()
def get_user(uid):
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())

    if not _require_admin(claims) and current_user_id != uid:
        return {"error": "Acceso denegado."}, 403

    user = User.query.get_or_404(uid)
    return {"user": user.to_dict()}, 200


@api_bp.route("/users/<int:uid>", methods=["PUT"])
@jwt_required()
def update_user(uid):
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())
    is_admin = _require_admin(claims)

    if not is_admin and current_user_id != uid:
        return {"error": "Acceso denegado."}, 403

    user = User.query.get_or_404(uid)
    body = request.get_json(silent=True) or {}

    if is_admin:
        if "name" in body:
            user.name = (body["name"] or "").strip() or user.name
        if "role" in body:
            new_role = body["role"]
            if new_role not in ("super_admin", "admin", "user"):
                return {"error": "Rol inválido."}, 400
            if new_role in ("admin", "super_admin") and claims.get("role") != "super_admin":
                return {"error": "Solo el super administrador puede asignar roles de administrador."}, 403
            user.role = new_role
        if "unit_id" in body:
            user.unit_id = body["unit_id"]
        if "is_active" in body:
            user.is_active = bool(body["is_active"])
    else:
        # Regular user can only update their own name
        if "name" in body:
            user.name = (body["name"] or "").strip() or user.name

    _log("update_user", current_user_id, uid)
    db.session.commit()
    return {"user": user.to_dict()}, 200


@api_bp.route("/users/<int:uid>", methods=["DELETE"])
@jwt_required()
def deactivate_user(uid):
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    current_user_id = int(get_jwt_identity())
    if current_user_id == uid:
        return {"error": "No puedes desactivar tu propia cuenta."}, 400

    user = User.query.get_or_404(uid)
    user.is_active = False
    _log("deactivate_user", current_user_id, uid, {"email": user.email})
    db.session.commit()
    return {"message": "Usuario desactivado."}, 200


@api_bp.route("/users/<int:uid>/reset-password", methods=["PUT"])
@jwt_required()
def reset_user_password(uid):
    """Admin resets a user's password (sends new temporary password or takes provided one)."""
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    user = User.query.get_or_404(uid)
    body = request.get_json(silent=True) or {}
    new_pw = body.get("new_password") or ""

    if not new_pw:
        # Generate a random secure password
        alphabet = string.ascii_letters + string.digits + "!@#$%"
        new_pw = "".join(secrets.choice(alphabet) for _ in range(12))

    if len(new_pw) < 8:
        return {"error": "La contraseña debe tener al menos 8 caracteres."}, 400

    user.set_password(new_pw)
    _log("reset_password", int(get_jwt_identity()), uid, {"target_email": user.email})
    db.session.commit()

    return {"message": "Contraseña actualizada.", "new_password": new_pw}, 200
