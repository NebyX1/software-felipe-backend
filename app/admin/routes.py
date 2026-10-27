"""
CivicFlow Flask HTML Admin Panel
Routes at /admin/...

Auth flow:
  GET/POST /admin/login    – email + password + math captcha → sends 2FA code
  GET/POST /admin/2fa      – verify 6-digit code → Flask-Login session
  GET      /admin/logout   – clear session

Protected routes (login_required + admin/super_admin role):
  GET      /admin/              → /admin/dashboard
  GET      /admin/dashboard     – KPI cards + recent activity
  GET/POST /admin/users         – list + create user
  GET/POST /admin/users/<id>/edit   – edit user (name, email, password, role, unit)
  POST     /admin/users/<id>/toggle  – toggle is_active
  POST     /admin/users/<id>/delete  – permanently delete user
  GET/POST /admin/units         – list + create unit
  GET/POST /admin/units/<id>/edit    – edit unit
  GET      /admin/logs          – activity log (super_admin only)
"""
import random
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import (
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
    current_app,
    abort,
)
from flask_login import login_user, logout_user, login_required, current_user

from . import admin_bp
from .forms import (
    AdminLoginForm,
    TwoFAForm,
    CreateUserForm,
    EditUserForm,
    CreateUnitForm,
    EditUnitForm,
)
from ..extensions import db
from ..models import User, TwoFactorCode, ActivityLog, Unit, Project, Task
from ..services.email_service import send_2fa_email

# ─── helpers ──────────────────────────────────────────────────────────────────


def _require_admin_role(f):
    """Decorator: allow only admin and super_admin users."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _require_super_admin(f):
    """Decorator: allow only super_admin users."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _log_admin(action: str, details: str | None = None):
    log = ActivityLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        username=current_user.name if current_user.is_authenticated else "SISTEMA",
        action=f"admin:{action}",
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string,
    )
    db.session.add(log)


def _unit_choices():
    """Return list of (id, name) tuples for unit select fields, with a blank option."""
    units = Unit.query.order_by(Unit.name).all()
    choices = [(0, "— Sin unidad —")] + [(u.id, f"{u.emoji}  {u.name}") for u in units]
    return choices


# ─── login ────────────────────────────────────────────────────────────────────


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for("admin.dashboard"))

    # Generate fresh math captcha on every GET
    if request.method == "GET" or "captcha_answer" not in session:
        a, b = random.randint(1, 20), random.randint(1, 20)
        session["captcha_answer"] = a + b
        session["captcha_question"] = f"{a} + {b} = ?"

    form = AdminLoginForm()
    if form.validate_on_submit():
        # Validate captcha first (before DB hit)
        if form.captcha.data != session.get("captcha_answer"):
            flash("Verificación de seguridad incorrecta.", "error")
            a, b = random.randint(1, 20), random.randint(1, 20)
            session["captcha_answer"] = a + b
            session["captcha_question"] = f"{a} + {b} = ?"
            return render_template("login.html", form=form,
                                   captcha_question=session["captcha_question"])

        user: User | None = User.query.filter_by(
            email=form.email.data.strip().lower(), is_active=True
        ).first()

        if not user or not user.check_password(form.password.data):
            flash("Credenciales incorrectas.", "error")
            a, b = random.randint(1, 20), random.randint(1, 20)
            session["captcha_answer"] = a + b
            session["captcha_question"] = f"{a} + {b} = ?"
            return render_template("login.html", form=form,
                                   captcha_question=session["captcha_question"])

        if not user.is_admin:
            flash("No tienes permisos de administrador.", "error")
            return render_template("login.html", form=form,
                                   captcha_question=session["captcha_question"])

        # Invalidate old pending codes, generate new
        TwoFactorCode.query.filter_by(user_id=user.id).filter(
            TwoFactorCode.consumed_at.is_(None)
        ).delete(synchronize_session=False)
        code_entry = TwoFactorCode.generate(user)
        db.session.commit()

        try:
            send_2fa_email(user.email, user.name, code_entry.code,
                           current_app._get_current_object())
        except Exception as exc:
            current_app.logger.error(f"Admin 2FA email error for {user.email}: {exc}")

        session["admin_pending_user_id"] = user.id
        session.pop("captcha_answer", None)
        session.pop("captcha_question", None)
        return redirect(url_for("admin.verify_2fa"))

    return render_template(
        "login.html",
        form=form,
        captcha_question=session.get("captcha_question", "? + ? = ?"),
    )


# ─── 2FA verification ─────────────────────────────────────────────────────────


@admin_bp.route("/2fa", methods=["GET", "POST"])
def verify_2fa():
    pending_id = session.get("admin_pending_user_id")
    if not pending_id:
        return redirect(url_for("admin.login"))

    form = TwoFAForm()
    if form.validate_on_submit():
        code_entry: TwoFactorCode | None = (
            TwoFactorCode.query
            .filter_by(user_id=pending_id)
            .filter(TwoFactorCode.consumed_at.is_(None))
            .order_by(TwoFactorCode.id.desc())
            .first()
        )
        if not code_entry or not code_entry.is_valid(form.code.data.strip()):
            flash("Código inválido o expirado.", "error")
            return render_template("verify_2fa.html", form=form)

        code_entry.used = True
        user: User = User.query.get(pending_id)
        user.last_login = datetime.now(timezone.utc)

        login_user(user, remember=False)
        session.pop("admin_pending_user_id", None)

        _log_admin("login_success")
        db.session.commit()

        return redirect(url_for("admin.dashboard"))

    return render_template("verify_2fa.html", form=form)


# ─── logout ───────────────────────────────────────────────────────────────────


@admin_bp.route("/logout")
@login_required
def logout():
    _log_admin("logout")
    db.session.commit()
    logout_user()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("admin.login"))


# ─── dashboard ────────────────────────────────────────────────────────────────


@admin_bp.route("/")
@admin_bp.route("/dashboard")
@login_required
@_require_admin_role
def dashboard():
    total_users = User.query.filter_by(is_active=True).count()
    total_units = Unit.query.count()
    active_projects = Project.query.filter_by(is_active=True).count()
    archived_projects = Project.query.filter_by(is_active=False).count()
    total_tasks = Task.query.count()

    tasks_by_status = {}
    for status in ("todo", "in_progress", "review", "done"):
        tasks_by_status[status] = Task.query.filter_by(status=status).count()

    recent_logs = (
        ActivityLog.query
        .order_by(ActivityLog.timestamp.desc())
        .limit(15)
        .all()
    )

    units_summary = []
    for unit in Unit.query.order_by(Unit.name).all():
        units_summary.append({
            "name": unit.name,
            "emoji": unit.emoji,
            "color": unit.color,
            "active_projects": unit.projects.filter_by(is_active=True).count(),
            "users": unit.users.filter_by(is_active=True).count(),
        })

    return render_template(
        "dashboard.html",
        total_users=total_users,
        total_units=total_units,
        active_projects=active_projects,
        archived_projects=archived_projects,
        total_tasks=total_tasks,
        tasks_by_status=tasks_by_status,
        recent_logs=recent_logs,
        units_summary=units_summary,
    )


# ─── users ────────────────────────────────────────────────────────────────────


@admin_bp.route("/users", methods=["GET", "POST"])
@login_required
@_require_admin_role
def users():
    form = CreateUserForm()
    form.unit_id.choices = _unit_choices()

    if form.validate_on_submit():
        unit_id = form.unit_id.data if form.unit_id.data else None
        if unit_id == 0:
            unit_id = None

        # Check duplicate email
        if User.query.filter_by(email=form.email.data.strip().lower()).first():
            flash("Ya existe un usuario con ese correo.", "error")
        else:
            new_user = User(
                name=form.name.data.strip(),
                email=form.email.data.strip().lower(),
                role=form.role.data,
                unit_id=unit_id,
            )
            new_user.set_password(form.password.data)
            db.session.add(new_user)
            _log_admin("create_user", f"email={new_user.email} role={new_user.role}")
            db.session.commit()
            flash(f"Usuario «{new_user.name}» creado exitosamente.", "success")
            return redirect(url_for("admin.users"))

    page = request.args.get("page", 1, type=int)
    per_page = 20
    pagination = (
        User.query
        .order_by(User.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return render_template(
        "users.html",
        users=pagination.items,
        pagination=pagination,
        form=form,
    )


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@_require_admin_role
def edit_user(user_id: int):
    user: User = User.query.get_or_404(user_id)
    form = EditUserForm(obj=user)
    form.unit_id.choices = _unit_choices()

    if form.validate_on_submit():
        # Super admin cannot be demoted/edited by a non-super-admin
        if user.is_super_admin and not current_user.is_super_admin:
            flash("No puedes editar un super administrador.", "error")
            return redirect(url_for("admin.users"))

        new_email = form.email.data.strip().lower()
        existing = User.query.filter_by(email=new_email).first()
        if existing and existing.id != user.id:
            flash("Ya existe otro usuario con ese correo.", "error")
            return render_template("edit_user.html", form=form, edit_user=user)

        old_email = user.email
        user.name = form.name.data.strip()
        user.email = new_email
        user.role = form.role.data
        user.unit_id = form.unit_id.data if form.unit_id.data else None
        if user.unit_id == 0:
            user.unit_id = None

        password_changed = bool(form.password.data)
        if password_changed:
            user.set_password(form.password.data)

        details = f"user_id={user.id} name={user.name} role={user.role}"
        if old_email != new_email:
            details += f" email={old_email}->{new_email}"
        if password_changed:
            details += " password_reset=1"
        _log_admin("edit_user", details)
        db.session.commit()
        flash(f"Usuario «{user.name}» actualizado.", "success")
        return redirect(url_for("admin.users"))

    # Pre-select current unit
    if user.unit_id:
        form.unit_id.data = user.unit_id
    else:
        form.unit_id.data = 0
    if request.method == "GET":
        form.email.data = user.email
        form.password.data = ""

    return render_template("edit_user.html", form=form, edit_user=user)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@_require_admin_role
def toggle_user(user_id: int):
    user: User = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("No puedes desactivar tu propia cuenta.", "error")
        return redirect(url_for("admin.users"))
    if user.is_super_admin and not current_user.is_super_admin:
        flash("No puedes desactivar a un super administrador.", "error")
        return redirect(url_for("admin.users"))

    user.is_active = not user.is_active
    action = "activate_user" if user.is_active else "deactivate_user"
    _log_admin(action, f"user_id={user.id} email={user.email}")
    db.session.commit()
    state = "activado" if user.is_active else "desactivado"
    flash(f"Usuario «{user.name}» {state}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@_require_admin_role
def delete_user(user_id: int):
    user: User = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("No puedes eliminar tu propia cuenta.", "error")
        return redirect(url_for("admin.users"))
    if user.is_super_admin and not current_user.is_super_admin:
        flash("No puedes eliminar a un super administrador.", "error")
        return redirect(url_for("admin.users"))

    name, email = user.name, user.email
    _log_admin("delete_user", f"user_id={user.id} name={name} email={email}")
    db.session.delete(user)
    db.session.commit()
    flash(f"Usuario «{name}» eliminado permanentemente.", "success")
    return redirect(url_for("admin.users"))


# ─── units ────────────────────────────────────────────────────────────────────


@admin_bp.route("/units", methods=["GET", "POST"])
@login_required
@_require_admin_role
def units():
    form = CreateUnitForm()

    if form.validate_on_submit():
        if Unit.query.filter_by(name=form.name.data.strip()).first():
            flash("Ya existe una unidad con ese nombre.", "error")
        else:
            unit = Unit(
                name=form.name.data.strip(),
                description=form.description.data.strip() if form.description.data else None,
                color=form.color.data.strip(),
                emoji=form.emoji.data.strip(),
            )
            db.session.add(unit)
            _log_admin("create_unit", f"name={unit.name}")
            db.session.commit()
            flash(f"Unidad «{unit.name}» creada.", "success")
            return redirect(url_for("admin.units"))

    all_units = Unit.query.order_by(Unit.name).all()
    units_data = []
    for u in all_units:
        units_data.append({
            "unit": u,
            "active_projects": u.projects.filter_by(is_active=True).count(),
            "archived_projects": u.projects.filter_by(is_active=False).count(),
            "users": u.users.filter_by(is_active=True).count(),
        })

    return render_template("units.html", units_data=units_data, form=form)


@admin_bp.route("/units/<int:unit_id>/edit", methods=["GET", "POST"])
@login_required
@_require_admin_role
def edit_unit(unit_id: int):
    unit: Unit = Unit.query.get_or_404(unit_id)
    form = EditUnitForm(obj=unit)

    if form.validate_on_submit():
        existing = Unit.query.filter_by(name=form.name.data.strip()).first()
        if existing and existing.id != unit.id:
            flash("Ya existe una unidad con ese nombre.", "error")
        else:
            unit.name = form.name.data.strip()
            unit.description = form.description.data.strip() if form.description.data else None
            unit.color = form.color.data.strip()
            unit.emoji = form.emoji.data.strip()
            _log_admin("edit_unit", f"unit_id={unit.id} name={unit.name}")
            db.session.commit()
            flash(f"Unidad «{unit.name}» actualizada.", "success")
            return redirect(url_for("admin.units"))

    return render_template("edit_unit.html", form=form, unit=unit)


# ─── logs ─────────────────────────────────────────────────────────────────────


@admin_bp.route("/logs")
@login_required
@_require_super_admin
def logs():
    page = request.args.get("page", 1, type=int)
    per_page = 50
    action_filter = request.args.get("action", "").strip()
    user_filter = request.args.get("user_id", "", type=str).strip()

    q = ActivityLog.query
    if action_filter:
        q = q.filter(ActivityLog.action.ilike(f"%{action_filter}%"))
    if user_filter.isdigit():
        q = q.filter(ActivityLog.user_id == int(user_filter))

    pagination = q.order_by(ActivityLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    all_users = User.query.order_by(User.name).all()

    return render_template(
        "logs.html",
        logs=pagination.items,
        pagination=pagination,
        action_filter=action_filter,
        user_filter=user_filter,
        all_users=all_users,
    )
