"""
Units (areas / departments) endpoints – admin+ only to create/update/delete.
  GET  /api/units          – list all units (all authenticated roles)
  POST /api/units          – create unit (admin+)
  GET  /api/units/<id>     – get unit details (all authenticated)
  PUT  /api/units/<id>     – update unit (admin+)
  DELETE /api/units/<id>   – delete unit (admin+)
"""
import re
from flask import request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from . import api_bp
from ..extensions import db
from ..models import Unit, ActivityLog


_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _is_admin_or_super(claims):
    return claims.get("role") in ("admin", "super_admin")


def _require_super_admin(claims):
    return claims.get("role") == "super_admin"


def _log(action, user_id, entity_id=None, details=None):
    import json as _json
    detail_str = None
    if details or entity_id is not None:
        d = {"entity_type": "unit"}
        if entity_id is not None:
            d["entity_id"] = entity_id
        if details:
            d.update(details)
        detail_str = _json.dumps(d, ensure_ascii=False)
    db.session.add(ActivityLog(
        user_id=user_id, action=action,
        details=detail_str, ip_address=request.remote_addr,
    ))


@api_bp.route("/units", methods=["GET"])
@jwt_required()
def list_units():
    claims = get_jwt()
    if _is_admin_or_super(claims):
        units = Unit.query.order_by(Unit.name).all()
        return {"units": [u.to_dict() for u in units]}, 200

    # Regular users can only see their assigned area
    unit_id = claims.get("unit_id")
    if not unit_id:
        return {"units": []}, 200

    unit = Unit.query.get(unit_id)
    if not unit:
        return {"units": []}, 200

    units = [unit]
    return {"units": [u.to_dict() for u in units]}, 200


@api_bp.route("/units", methods=["POST"])
@jwt_required()
def create_unit():
    claims = get_jwt()
    if not _require_super_admin(claims):
        return {"error": "Acceso denegado. Solo super administradores."}, 403

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return {"error": "El nombre es requerido."}, 400

    if Unit.query.filter_by(name=name).first():
        return {"error": "Ya existe una unidad con ese nombre."}, 409

    color = (body.get("color") or "#6366f1").strip()
    if not _HEX_COLOR_RE.match(color):
        return {"error": "Color inválido. Debe ser formato #RRGGBB."}, 400

    unit = Unit(
        name=name,
        description=(body.get("description") or "").strip() or None,
        color=color,
        emoji=(body.get("emoji") or "🏛️").strip()[:8] or "🏛️",
    )
    db.session.add(unit)
    db.session.flush()
    _log("create_unit", int(get_jwt_identity()), unit.id, {"name": name})
    db.session.commit()
    return {"unit": unit.to_dict()}, 201


@api_bp.route("/units/<int:uid>", methods=["GET"])
@jwt_required()
def get_unit(uid):
    unit = Unit.query.get_or_404(uid)
    return {"unit": unit.to_dict()}, 200


@api_bp.route("/units/<int:uid>", methods=["PUT"])
@jwt_required()
def update_unit(uid):
    claims = get_jwt()
    if not _require_super_admin(claims):
        return {"error": "Acceso denegado."}, 403

    unit = Unit.query.get_or_404(uid)
    body = request.get_json(silent=True) or {}

    if "name" in body:
        new_name = (body["name"] or "").strip()
        if not new_name:
            return {"error": "El nombre no puede estar vacío."}, 400
        existing = Unit.query.filter(
            Unit.name == new_name,
            Unit.id != uid,
        ).first()
        if existing:
            return {"error": "Ya existe una unidad con ese nombre."}, 409
        unit.name = new_name

    if "description" in body:
        unit.description = (body["description"] or "").strip() or None
    if "color" in body:
        color = (body["color"] or "").strip()
        if not _HEX_COLOR_RE.match(color):
            return {"error": "Color inválido. Debe ser formato #RRGGBB."}, 400
        unit.color = color
    if "emoji" in body:
        unit.emoji = (body["emoji"] or "🏛️").strip()[:8] or "🏛️"

    _log("update_unit", int(get_jwt_identity()), uid)
    db.session.commit()
    return {"unit": unit.to_dict()}, 200


@api_bp.route("/units/<int:uid>", methods=["DELETE"])
@jwt_required()
def delete_unit(uid):
    claims = get_jwt()
    if not _require_super_admin(claims):
        return {"error": "Acceso denegado."}, 403

    unit = Unit.query.get_or_404(uid)

    # Prevent deletion if active projects exist
    if unit.projects.filter_by(is_active=True).count() > 0:
        msg = "No se puede eliminar: la unidad tiene proyectos activos."
        return {"error": msg}, 409

    _log("delete_unit", int(get_jwt_identity()), uid, {"name": unit.name})
    db.session.delete(unit)
    db.session.commit()
    return {"message": "Unidad eliminada."}, 200
