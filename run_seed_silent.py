from app import create_app
from app.extensions import db
from app.commands import TASKS_DATA, WORKS_DATA, USERS_DATA, UNITS_DATA, PROJECTS_DATA, _days
from app.models.user import User
from app.models.unit import Unit
from app.models.project import Project
from app.models.task import Task
from app.models.work import Work

print("Iniciando seed silencioso...")
app = create_app()

with app.app_context():
    # Vaciando base
    print("Vaciando base de datos...")
    
    demo_emails = [u[1] for u in USERS_DATA]
    demo_unit_names = [u["name"] for u in UNITS_DATA]
    
    existing_users = User.query.filter(User.email.in_(demo_emails)).all()
    for u in existing_users:
        db.session.delete(u)
    existing_units = Unit.query.filter(Unit.name.in_(demo_unit_names)).all()
    for unit in existing_units:
        db.session.delete(unit)
    db.session.commit()

    print("Creando unidades...")
    units = {}
    for ud in UNITS_DATA:
        if Unit.query.filter_by(name=ud["name"]).first():
            units[ud["name"]] = Unit.query.filter_by(name=ud["name"]).first()
            continue
        unit = Unit(name=ud["name"], description=ud["description"], color=ud["color"], emoji=ud.get("emoji") or "🛠️")
        db.session.add(unit)
        db.session.flush()
        units[ud["name"]] = unit
    for ud in UNITS_DATA:
        existing_unit = units.get(ud["name"])
        if existing_unit:
            existing_unit.emoji = ud.get("emoji") or existing_unit.emoji or "🛠️"
    db.session.commit()

    print("Creando usuarios...")
    user_map = {}
    for name, email, password, role, unit_name in USERS_DATA:
        if User.query.filter_by(email=email).first():
            user_map[email] = User.query.filter_by(email=email).first()
            continue
        u = User(name=name, email=email, role=role, unit_id=units[unit_name].id if unit_name else None)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        user_map[email] = u
    db.session.commit()

    print("Creando proyectos...")
    project_map = {}
    for pname, pdesc, unit_name, creator_email, is_active in PROJECTS_DATA:
        if Project.query.filter_by(name=pname).first():
            project_map[pname] = Project.query.filter_by(name=pname).first()
            continue
        p = Project(name=pname, description=pdesc, unit_id=units[unit_name].id, created_by=user_map[creator_email].id, is_active=is_active)
        db.session.add(p)
        db.session.flush()
        project_map[pname] = p
    db.session.commit()

    print("Creando tareas (con no_autoflush)...")
    task_count = 0
    with db.session.no_autoflush:
        for pname, title, description, status, priority, responsible, due_offset in TASKS_DATA:
            if pname not in project_map:
                continue
            pid = project_map[pname].id
            if Task.query.filter_by(project_id=pid, title=title).first():
                continue
            t = Task(project_id=pid, title=title, description=description, status=status, priority=priority, responsible=responsible, due_date=_days(due_offset))
            db.session.add(t)
            task_count += 1
    db.session.commit()
    print("Tareas creadas: ", task_count)

    print("Creando obras (con no_autoflush)...")
    works_created = 0
    with db.session.no_autoflush:
        for wd in WORKS_DATA:
            unit = units.get(wd["unit_name"])
            creator = user_map.get(wd["creator_email"])
            if not unit or not creator:
                continue
            exists = Work.query.filter_by(unit_id=unit.id, title=wd["title"]).first()
            if exists:
                continue
            work = Work(unit_id=unit.id, title=wd["title"], description=wd["description"], status=wd["status"], progress=wd["progress"], location=wd["location"], start_date=_days(wd["start_offset"]), end_date=_days(wd["end_offset"]), budget=wd["budget"], created_by=creator.id)
            db.session.add(work)
            works_created += 1
    db.session.commit()
    print("Obras creadas: ", works_created)

    print("--- Seed finalizado exitosamente. ---")
