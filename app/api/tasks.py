"""
Task endpoints:
  GET  /api/tasks?project_id=<id>   – list tasks of a project
  POST /api/tasks                   – create task
  GET  /api/tasks/<id>              – task detail
  PUT  /api/tasks/<id>              – update task (all fields)
  PATCH /api/tasks/<id>/status      – update status only (drag-drop)
  DELETE /api/tasks/<id>            – delete task
"""
from flask import request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from . import api_bp
from ..extensions import db
from ..models import Project, Task, ActivityLog
from .projects import _can_access_project

VALID_STATUSES = ("todo", "in_progress", "review", "done")
VALID_PRIORITIES = ("low", "medium", "high", "urgent")


def _log(action, user_id, entity_id=None, details=None):
    import json as _json
    detail_str = None
    if details or entity_id is not None:
        d = {"entity_type": "task"}
        if entity_id is not None:
            d["entity_id"] = entity_id
        if details:
            d.update(details)
        detail_str = _json.dumps(d, ensure_ascii=False)
    db.session.add(ActivityLog(
        user_id=user_id, action=action,
        details=detail_str, ip_address=request.remote_addr,
    ))


@api_bp.route("/tasks", methods=["GET"])
@jwt_required()
def list_tasks():
    claims = get_jwt()
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return {"error": "project_id es requerido."}, 400

    project = Project.query.get_or_404(project_id)
    if not _can_access_project(project, claims):
        return {"error": "No tienes acceso a este proyecto."}, 403

    tasks = Task.query.filter_by(project_id=project_id).order_by(Task.created_at).all()
    return {"tasks": [t.to_dict() for t in tasks]}, 200


@api_bp.route("/tasks", methods=["POST"])
@jwt_required()
def create_task():
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}

    project_id = body.get("project_id")
    if not project_id:
        return {"error": "project_id es requerido."}, 400

    project = Project.query.get_or_404(project_id)
    if not _can_access_project(project, claims):
        return {"error": "No tienes acceso a este proyecto."}, 403

    title = (body.get("title") or "").strip()
    if not title:
        return {"error": "El título de la tarea es requerido."}, 400

    status = body.get("status") or "todo"
    priority = body.get("priority") or "medium"
    if status not in VALID_STATUSES:
        return {"error": f"Estado inválido. Opciones: {VALID_STATUSES}"}, 400
    if priority not in VALID_PRIORITIES:
        return {"error": f"Prioridad inválida. Opciones: {VALID_PRIORITIES}"}, 400

    due_date = None
    if body.get("due_date"):
        from datetime import date
        try:
            due_date = date.fromisoformat(body["due_date"])
        except ValueError:
            return {"error": "Formato de fecha inválido (YYYY-MM-DD)."}, 400

    task = Task(
        project_id=project_id,
        title=title,
        description=(body.get("description") or "").strip() or None,
        status=status,
        priority=priority,
        responsible=(body.get("responsible") or "").strip() or None,
        due_date=due_date,
    )
    db.session.add(task)
    db.session.flush()
    _log("create_task", current_user_id, task.id, {"title": title, "project_id": project_id})
    db.session.commit()
    return {"task": task.to_dict()}, 201


@api_bp.route("/tasks/<int:tid>", methods=["GET"])
@jwt_required()
def get_task(tid):
    claims = get_jwt()
    task = Task.query.get_or_404(tid)
    if not _can_access_project(task.project, claims):
        return {"error": "No tienes acceso a esta tarea."}, 403
    return {"task": task.to_dict()}, 200


@api_bp.route("/tasks/<int:tid>", methods=["PUT"])
@jwt_required()
def update_task(tid):
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())
    task = Task.query.get_or_404(tid)

    if not _can_access_project(task.project, claims):
        return {"error": "No tienes acceso a esta tarea."}, 403

    body = request.get_json(silent=True) or {}

    if "title" in body:
        t = (body["title"] or "").strip()
        if not t:
            return {"error": "El título no puede estar vacío."}, 400
        task.title = t

    if "description" in body:
        task.description = (body["description"] or "").strip() or None

    if "status" in body:
        if body["status"] not in VALID_STATUSES:
            return {"error": "Estado inválido."}, 400
        task.status = body["status"]

    if "priority" in body:
        if body["priority"] not in VALID_PRIORITIES:
            return {"error": "Prioridad inválida."}, 400
        task.priority = body["priority"]

    if "responsible" in body:
        task.responsible = (body["responsible"] or "").strip() or None

    if "due_date" in body:
        if body["due_date"]:
            from datetime import date
            try:
                task.due_date = date.fromisoformat(body["due_date"])
            except ValueError:
                return {"error": "Formato de fecha inválido (YYYY-MM-DD)."}, 400
        else:
            task.due_date = None

    _log("update_task", current_user_id, tid)
    db.session.commit()
    return {"task": task.to_dict()}, 200


@api_bp.route("/tasks/<int:tid>/status", methods=["PATCH"])
@jwt_required()
def update_task_status(tid):
    """Lightweight endpoint for drag-and-drop status updates."""
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())
    task = Task.query.get_or_404(tid)

    if not _can_access_project(task.project, claims):
        return {"error": "No tienes acceso a esta tarea."}, 403

    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if not new_status or new_status not in VALID_STATUSES:
        return {"error": "Estado inválido."}, 400

    task.status = new_status
    _log("update_task_status", current_user_id, tid, {"status": new_status})
    db.session.commit()
    return {"task": task.to_dict()}, 200


@api_bp.route("/tasks/<int:tid>", methods=["DELETE"])
@jwt_required()
def delete_task(tid):
    claims = get_jwt()
    current_user_id = int(get_jwt_identity())
    task = Task.query.get_or_404(tid)

    if not _can_access_project(task.project, claims):
        return {"error": "No tienes acceso a esta tarea."}, 403

    _log("delete_task", current_user_id, tid, {"title": task.title})
    db.session.delete(task)
    db.session.commit()
    return {"message": "Tarea eliminada."}, 200
