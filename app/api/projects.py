"""
Project endpoints with role-based access:
  - user: sees only their unit's projects
  - admin/super_admin: sees all projects

  GET  /api/projects               – list projects
  POST /api/projects               – create project
  GET  /api/projects/<id>          – project detail
  PUT  /api/projects/<id>          – update/archive project
  DELETE /api/projects/<id>        – delete project (admin+)
"""
from flask import request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from . import api_bp
from ..extensions import db
from ..models import Project, Unit, ActivityLog


def _log(action, user_id, entity_id=None, details=None):
    import json as _json
    detail_str = None
    if details or entity_id is not None:
        d = {"entity_type": "project"}
        if entity_id is not None:
            d["entity_id"] = entity_id
        if details:
            d.update(details)
        detail_str = _json.dumps(d, ensure_ascii=False)
    db.session.add(ActivityLog(
        user_id=user_id, action=action,
        details=detail_str, ip_address=request.remote_addr,
    ))


def _can_access_project(project: Project, claims: dict) -> bool:
    """Return True if the caller may read/write this project."""
    role = claims.get("role")
    if role in ("admin", "super_admin"):
        return True
    return project.unit_id == claims.get("unit_id")


@api_bp.route("/projects", methods=["GET"])
@jwt_required()
def list_projects():
    claims = get_jwt()
    role = claims.get("role")
    archived = request.args.get("archived", "false").lower() == "true"

    q = Project.query.filter_by(is_active=not archived)

    if role not in ("admin", "super_admin"):
        unit_id = claims.get("unit_id")
        if not unit_id:
            return {"projects": []}, 200
        q = q.filter_by(unit_id=unit_id)
    else:
        unit_filter = request.args.get("unit_id", type=int)
        if unit_filter:
            q = q.filter_by(unit_id=unit_filter)

    projects = q.order_by(Project.updated_at.desc()).all()
    return {"projects": [p.to_dict() for p in projects]}, 200


@api_bp.route("/projects", methods=["POST"])
@jwt_required()
def create_project():
    claims = get_jwt()
    role = claims.get("role")
    current_user_id = int(get_jwt_identity())

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip() or None

    if not name:
        return {"error": "El nombre del proyecto es requerido."}, 400

    # Determine unit
    if role in ("admin", "super_admin"):
        unit_id = body.get("unit_id")
        if not unit_id:
            return {"error": "Los administradores deben especificar la unidad."}, 400
    else:
        unit_id = claims.get("unit_id")
        if not unit_id:
            return {"error": "Tu usuario no tiene unidad asignada."}, 400

    if not Unit.query.get(unit_id):
        return {"error": "Unidad no encontrada."}, 404

    project = Project(
        name=name,
        description=description,
        unit_id=unit_id,
        created_by=current_user_id,
    )
    db.session.add(project)
    db.session.flush()
    _log("create_project", current_user_id, project.id, {"name": name, "unit_id": unit_id})
    db.session.commit()
    return {"project": project.to_dict()}, 201


@api_bp.route("/projects/<int:pid>", methods=["GET"])
@jwt_required()
def get_project(pid):
    claims = get_jwt()
    project = Project.query.get_or_404(pid)

    if not _can_access_project(project, claims):
        return {"error": "No tienes acceso a este proyecto."}, 403

    return {"project": project.to_dict(include_task_count=True)}, 200


@api_bp.route("/projects/<int:pid>", methods=["PUT"])
@jwt_required()
def update_project(pid):
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())
    project = Project.query.get_or_404(pid)

    if not _can_access_project(project, claims):
        return {"error": "No tienes acceso a este proyecto."}, 403

    body = request.get_json(silent=True) or {}

    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            return {"error": "El nombre no puede estar vacío."}, 400
        project.name = name

    if "description" in body:
        project.description = (body["description"] or "").strip() or None

    if "is_active" in body:
        project.is_active = bool(body["is_active"])

    # Admin+ can reassign unit
    if "unit_id" in body and claims.get("role") in ("admin", "super_admin"):
        if not Unit.query.get(body["unit_id"]):
            return {"error": "Unidad no encontrada."}, 404
        project.unit_id = body["unit_id"]

    _log("update_project", current_user_id, pid, {"name": project.name})
    db.session.commit()
    return {"project": project.to_dict()}, 200


@api_bp.route("/projects/<int:pid>", methods=["DELETE"])
@jwt_required()
def delete_project(pid):
    claims = get_jwt()
    if claims.get("role") not in ("admin", "super_admin"):
        return {"error": "Solo administradores pueden eliminar proyectos."}, 403

    project = Project.query.get_or_404(pid)
    _log("delete_project", int(get_jwt_identity()), pid, {"name": project.name})
    db.session.delete(project)
    db.session.commit()
    return {"message": "Proyecto eliminado."}, 200
