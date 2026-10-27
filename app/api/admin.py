"""
Admin-only endpoints:
  GET /api/admin/dashboard         – summary stats (admin+)
  GET /api/admin/logs              – activity logs (super_admin only)
  GET /api/admin/export/projects   – CSV export of projects
  GET /api/admin/export/tasks      – CSV export of tasks
"""
import csv
import io
from datetime import datetime

from flask import request, Response
from flask_jwt_extended import jwt_required, get_jwt

from . import api_bp
from ..models import User, Unit, Project, Task, ActivityLog


def _require_admin(claims):
    return claims.get("role") in ("admin", "super_admin")


def _require_super_admin(claims):
    return claims.get("role") == "super_admin"


@api_bp.route("/admin/dashboard", methods=["GET"])
@jwt_required()
def admin_dashboard():
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    unit_id = request.args.get("unit_id", type=int)

    total_users = User.query.filter_by(is_active=True).count()
    total_units = Unit.query.count()
    total_projects = Project.query.filter_by(is_active=True).count()
    archived_projects = Project.query.filter_by(is_active=False).count()

    tasks_query = Task.query.join(Project)
    if unit_id:
        tasks_query = tasks_query.filter(Project.unit_id == unit_id)

    total_tasks = tasks_query.count()

    # Tasks by status
    tasks_by_status = {}
    for status in ("todo", "in_progress", "review", "done"):
        tasks_by_status[status] = (
            tasks_query.filter(Task.status == status).count()
        )

    # Tasks by priority
    tasks_by_priority = {}
    for priority in ("low", "medium", "high", "urgent"):
        tasks_by_priority[priority] = (
            tasks_query.filter(Task.priority == priority).count()
        )

    # Projects per unit
    units_data = []
    for unit in Unit.query.order_by(Unit.name).all():
        units_data.append({
            "id": unit.id,
            "name": unit.name,
            "color": unit.color,
            "active_projects": unit.projects.filter_by(is_active=True).count(),
            "archived_projects": (
                unit.projects.filter_by(is_active=False).count()
            ),
            "users": unit.users.filter_by(is_active=True).count(),
        })

    # Recent activity (last 20 entries)
    recent_logs = (
        ActivityLog.query
        .order_by(ActivityLog.timestamp.desc())
        .limit(20)
        .all()
    )

    return {
        "stats": {
            "total_users": total_users,
            "total_units": total_units,
            "total_projects": total_projects,
            "archived_projects": archived_projects,
            "total_tasks": total_tasks,
            "tasks_by_status": tasks_by_status,
            "tasks_by_priority": tasks_by_priority,
        },
        "units": units_data,
        "recent_activity": [log.to_dict() for log in recent_logs],
    }, 200


@api_bp.route("/admin/logs", methods=["GET"])
@jwt_required()
def admin_logs():
    claims = get_jwt()
    if not _require_super_admin(claims):
        return {"error": "Acceso denegado. Solo super administradores."}, 403

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    action_filter = request.args.get("action")
    user_id_filter = request.args.get("user_id", type=int)
    entity_type_filter = request.args.get("entity_type")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    q = ActivityLog.query

    if action_filter:
        q = q.filter(ActivityLog.action.ilike(f"%{action_filter}%"))
    if user_id_filter:
        q = q.filter_by(user_id=user_id_filter)
    if entity_type_filter:
        q = q.filter(
            ActivityLog.details.ilike(
                f'%"entity_type": "{entity_type_filter}"%'
            )
        )
    if date_from:
        try:
            q = q.filter(
                ActivityLog.timestamp >= datetime.fromisoformat(date_from)
            )
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(
                ActivityLog.timestamp <= datetime.fromisoformat(date_to)
            )
        except ValueError:
            pass

    paginated = q.order_by(ActivityLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return {
        "logs": [log.to_dict() for log in paginated.items],
        "pagination": {
            "page": paginated.page,
            "per_page": per_page,
            "total": paginated.total,
            "pages": paginated.pages,
        },
    }, 200


@api_bp.route("/admin/export/projects", methods=["GET"])
@jwt_required()
def export_projects():
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    unit_id = request.args.get("unit_id", type=int)
    archived_param = request.args.get("archived")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    q = Project.query
    if unit_id:
        q = q.filter_by(unit_id=unit_id)
    if archived_param == "true":
        q = q.filter_by(is_active=False)
    elif archived_param == "false":
        q = q.filter_by(is_active=True)
    if date_from:
        try:
            q = q.filter(
                Project.created_at >= datetime.fromisoformat(date_from)
            )
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(Project.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    projects = q.order_by(Project.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Nombre", "Unidad", "Estado",
        "Creado por", "Tareas total", "Fecha creación", "Última actualización",
    ])
    for p in projects:
        writer.writerow([
            p.id, p.name,
            p.unit.name if p.unit else "",
            "Activo" if p.is_active else "Archivado",
            p.creator.name if p.creator else "",
            p.tasks.count(),
            p.created_at.strftime("%Y-%m-%d %H:%M"),
            p.updated_at.strftime("%Y-%m-%d %H:%M"),
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=proyectos.csv"},
    )


@api_bp.route("/admin/export/tasks", methods=["GET"])
@jwt_required()
def export_tasks():
    claims = get_jwt()
    if not _require_admin(claims):
        return {"error": "Acceso denegado."}, 403

    project_id = request.args.get("project_id", type=int)
    unit_id = request.args.get("unit_id", type=int)
    status_filter = request.args.get("status")
    priority_filter = request.args.get("priority")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    q = Task.query.join(Project)
    if project_id:
        q = q.filter(Task.project_id == project_id)
    if unit_id:
        q = q.filter(Project.unit_id == unit_id)
    if status_filter:
        q = q.filter(Task.status == status_filter)
    if priority_filter:
        q = q.filter(Task.priority == priority_filter)
    if date_from:
        try:
            q = q.filter(Task.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(Task.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    tasks = q.order_by(Task.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Título", "Proyecto", "Unidad",
        "Estado", "Prioridad", "Responsable",
        "Fecha límite", "Fecha creación",
    ])
    for t in tasks:
        writer.writerow([
            t.id, t.title,
            t.project.name if t.project else "",
            t.project.unit.name if t.project and t.project.unit else "",
            t.status, t.priority,
            t.responsible or "",
            t.due_date.isoformat() if t.due_date else "",
            t.created_at.strftime("%Y-%m-%d %H:%M"),
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tareas.csv"},
    )
