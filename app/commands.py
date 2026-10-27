import click
from datetime import date, timedelta
from flask.cli import with_appcontext
from sqlalchemy import inspect, text
from .extensions import db
from .models.user import User
from .models.unit import Unit
from .models.project import Project
from .models.task import Task
from .models.work import Work


@click.command("create-admin")
@click.argument("name")
@click.argument("email")
@click.argument("password")
@click.argument("is_super_admin", default="false")
@with_appcontext
def create_admin(name, email, password, is_super_admin):
    """Crea un usuario administrador.

    Usage: flask create-admin "Nombre" email@ejemplo.com contraseña true/false
    """
    is_super = is_super_admin.lower() == "true"
    role = "super_admin" if is_super else "admin"

    if User.query.filter_by(email=email.lower()).first():
        click.echo(f"[ERROR] Ya existe un usuario con el email '{email}'.")
        return

    user = User(name=name, email=email.lower(), role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    label = "Super Administrador" if is_super else "Administrador"
    click.echo(f"[OK] {label} '{name}' ({email}) creado exitosamente.")


@click.command("init-db")
@with_appcontext
def init_db():
    """Crea todas las tablas en la base de datos."""
    db.create_all()
    click.echo("[OK] Base de datos inicializada.")


@click.command("sync-schema")
@with_appcontext
def sync_schema():
    """Sincroniza columnas/tablas críticas sin depender de Alembic."""
    inspector = inspect(db.engine)

    # Ensure units.emoji exists
    if inspector.has_table("units"):
        unit_cols = {c["name"] for c in inspector.get_columns("units")}
        if "emoji" not in unit_cols:
            db.session.execute(
                text(
                    "ALTER TABLE units ADD COLUMN emoji VARCHAR(16) "
                    "NOT NULL DEFAULT '…'"
                )
            )
            db.session.execute(
                text("UPDATE units SET emoji = '…' WHERE emoji IS NULL OR emoji = ''")
            )
            click.echo("[OK] Columna units.emoji creada.")

    # Ensure works module tables exist
    existing_tables = set(inspector.get_table_names())
    required_work_tables = {
        'works',
        'work_documents',
        'work_tasks',
        'work_task_documents',
    }
    if not required_work_tables.issubset(existing_tables):
        db.create_all()
        click.echo("[OK] Tablas del modulo obras sincronizadas.")

    # Repair any stale FK still pointing to legacy admin_users table.
    if "users" in existing_tables:
        for table_name in sorted(existing_tables):
            fk_list = inspector.get_foreign_keys(table_name)
            for fk in fk_list:
                if fk.get("referred_table") != "admin_users":
                    continue

                constrained_columns = fk.get("constrained_columns") or []
                referred_columns = fk.get("referred_columns") or []
                if len(constrained_columns) != 1 or referred_columns != ["id"]:
                    continue

                col_name = constrained_columns[0]
                fk_name = (fk.get("name") or "").replace("`", "")
                if fk_name:
                    db.session.execute(
                        text(
                            f"ALTER TABLE `{table_name}` "
                            f"DROP FOREIGN KEY `{fk_name}`"
                        )
                    )

                new_fk_name = f"fk_{table_name}_{col_name}_users"
                if len(new_fk_name) > 60:
                    new_fk_name = new_fk_name[:60]

                ondelete = (fk.get("options") or {}).get("ondelete")
                ondelete_sql = f" ON DELETE {ondelete}" if ondelete else ""

                db.session.execute(
                    text(
                        f"ALTER TABLE `{table_name}` "
                        f"ADD CONSTRAINT `{new_fk_name}` "
                        f"FOREIGN KEY (`{col_name}`) REFERENCES `users`(`id`){ondelete_sql}"
                    )
                )

                click.echo(
                    f"[OK] FK {table_name}.{col_name} reparada para apuntar a users.id."
                )

    db.session.commit()
    click.echo("[OK] Sincronización de esquema finalizada.")


@click.command("repair-alembic")
@with_appcontext
def repair_alembic():
    """Repara alembic_version cuando quedó apuntando a una revisión faltante."""
    db.session.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
    current = db.session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    target = "20260311_add_works_module"

    if current:
        db.session.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": target})
    else:
        db.session.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": target})

    db.session.commit()
    click.echo(f"[OK] alembic_version reparada a {target}.")


# ---------------------------------------------------------------------------
# seed-demo - Datos de prueba completos
# ---------------------------------------------------------------------------

TODAY = date.today()


def _days(n: int) -> date:
    return TODAY + timedelta(days=n)


UNITS_DATA = [
    {"name": "Dirección General",       "description": "Dirección y coordinación estratégica de la organización",    "color": "#6366f1", "emoji": "🏦"},
    {"name": "Recursos Humanos",       "description": "Gestión de personal, vínculos laborales y capacitación",         "color": "#0ea5e9", "emoji": "📂"},
    {"name": "Departamento Legal",     "description": "Liquidaciones, contratos y encuadramiento normativo",           "color": "#f59e0b", "emoji": "⚖️"},
    {"name": "Administración",         "description": "Gestión administrativa, archivo y soporte operativo",           "color": "#10b981", "emoji": "📄"},
]

WORKS_DATA = [
    {
        "unit_name": "Recursos Humanos",
        "title": "Programa de Actualización de Legajos",
        "description": "Digitalización y actualización de legajos del personal activo.",
        "status": "in_progress",
        "progress": 55,
        "location": "N/A",
        "start_offset": -45,
        "end_offset": 30,
        "budget": None,
        "creator_email": "laura@demo.com",
    },
    {
        "unit_name": "Departamento Legal",
        "title": "Revisión de Contratos Vigentes 2026",
        "description": "Auditoría de todos los contratos activos para detectar vencimientos y renovaciones.",
        "status": "planning",
        "progress": 10,
        "location": "N/A",
        "start_offset": 5,
        "end_offset": 90,
        "budget": None,
        "creator_email": "juan@demo.com",
    },
    {
        "unit_name": "Administración",
        "title": "Migración al Sistema de Gestión Digital",
        "description": "Traslado de expedientes físicos al sistema informativo centralizado.",
        "status": "paused",
        "progress": 38,
        "location": "Archivo Central",
        "start_offset": -60,
        "end_offset": 20,
        "budget": None,
        "creator_email": "maria@demo.com",
    },
]

USERS_DATA = [
    # (name, email, password, role, unit_name)
    ("Super Administrador",      "super@demo.com",    "Demo1234!",  "super_admin", None),
    ("Director de RRHH",         "director@demo.com", "Demo1234!",  "admin",       None),
    ("Laura González",           "laura@demo.com",    "Demo1234!",  "user",        "Recursos Humanos"),
    ("Carlos Fernández",         "carlos@demo.com",   "Demo1234!",  "user",        "Recursos Humanos"),
    ("María López",             "maria@demo.com",    "Demo1234!",  "user",        "Administración"),
    ("Juan Martínez",            "juan@demo.com",     "Demo1234!",  "user",        "Departamento Legal"),
    ("Ana Torres",               "ana@demo.com",      "Demo1234!",  "user",        "Dirección General"),
]

PROJECTS_DATA = [
    # (name, description, unit_name, creator_email, is_active)
    ("Alta de Personal Ingresante",            "Proceso de incorporación de nuevos agentes: legajo, encuadramiento y alta AFIP.",          "Recursos Humanos",  "laura@demo.com",   True),
    ("Evaluación de Desempeño 2026",           "Relevamiento de indicadores de gestión del personal durante el año en curso.",            "Recursos Humanos",  "carlos@demo.com",  True),
    ("Actualización de Escalafón",              "Revisión y actualización de categorías y antigüedades del personal.",                    "Recursos Humanos",  "laura@demo.com",   True),
    ("Programa de Capacitación Anual",          "Diseño y ejecución del plan de capacitación obligatoria 2026.",                         "Recursos Humanos",  "carlos@demo.com",  True),
    ("Relevamiento de Ausentismo Q1",           "Análisis de inasistencias, licencias y justificaciones del primer trimestre.",            "Recursos Humanos",  "laura@demo.com",   False),
    ("Contratos y Convenios Colectivos",        "Seguimiento de convenios de trabajo y renovación de contratos por vencimiento.",          "Departamento Legal", "juan@demo.com",    True),
    ("Liquidación de Haberes Marzo",            "Procesamiento y control de la liquidación mensual de sueldos.",                         "Departamento Legal", "juan@demo.com",    True),
    ("Tramitación de Bajas y Jubilaciones",     "Expedientes de personal que inicia proceso de baja o retiro.",                          "Departamento Legal", "juan@demo.com",    True),
    ("Actualización de Expedientes Digitales", "Digitalización de documentación histórica del archivo de personal.",                     "Administración",   "maria@demo.com",   True),
    ("Registro de Licencias Especiales",        "Control y documentación de licencias por maternidad, enfermedad y causas especiales.",   "Administración",   "maria@demo.com",   True),
]

TASKS_DATA = [
    # (project_name, title, description, status, priority, responsible, due_offset_days)
    # --- Alta de Personal Ingresante ---
    ("Alta de Personal Ingresante", "Recepción de documentación",           "Verificar DNI, título, CUIL y antecedentes laborales.",                     "done",        "high",   "Laura González",  -15),
    ("Alta de Personal Ingresante", "Carga en Sistema de RRHH",            "Ingreso de datos personales y laborales al sistema.",                        "done",        "high",   "Carlos Fernández", -10),
    ("Alta de Personal Ingresante", "Notificación a AFIP",                  "Alta temprana y empadronamiento en Sistema de Registración Laboral.",        "in_progress", "urgent", "Laura González",   3),
    ("Alta de Personal Ingresante", "Confeccionar legajo físico",           "Armado de carpeta con documentación original y copias certificadas.",        "in_progress", "high",   "Carlos Fernández",  7),
    ("Alta de Personal Ingresante", "Entregar credencial y accesos",        "Generar credencial, usuario de sistema y acceso al edificio.",               "todo",        "medium", "Laura González",   12),
    ("Alta de Personal Ingresante", "Inducición y circuito de firma",       "Entrega de reglamento interno y firma de recepón.",                         "todo",        "low",    "Carlos Fernández",  18),

    # --- Evaluación de Desempeño 2026 ---
    ("Evaluación de Desempeño 2026", "Definir indicadores de evaluación",   "Consensuar con dirección los criterios de valoración.",                     "done",        "high",   "Carlos Fernández", -25),
    ("Evaluación de Desempeño 2026", "Distribuir formularios al personal",  "Enviar planillas de autoevaluación y evaluación de superiores.",             "done",        "high",   "Laura González",  -12),
    ("Evaluación de Desempeño 2026", "Recolección de formularios",          "Consolidar respuestas y validar completitud.",                              "in_progress", "high",   "Carlos Fernández",  5),
    ("Evaluación de Desempeño 2026", "Análisis de resultados",             "Procesar datos y generar informe por área.",                                "todo",        "medium", "Laura González",   15),
    ("Evaluación de Desempeño 2026", "Devolución a cada agente",           "Entrevista individual de feedback con superior inmediato.",                 "todo",        "medium", "Carlos Fernández",  25),

    # --- Actualización de Escalafón ---
    ("Actualización de Escalafón", "Relevar legajos de antiguedad",        "Verificar fecha de ingreso y categoría actual de cada agente.",             "done",        "high",   "Laura González",  -20),
    ("Actualización de Escalafón", "Cruzar con convenio colectivo",       "Comparar categorías actuales con tabla escalafonaria vigente.",             "review",      "high",   "Carlos Fernández",  2),
    ("Actualización de Escalafón", "Proponer ascensos y correcciones",    "Emitir listado de personal con ascenso propuesto.",                         "in_progress", "urgent", "Laura González",   8),
    ("Actualización de Escalafón", "Elevar propuesta a Dirección",       "Informe formal para aprobación de la Dirección General.",                   "todo",        "high",   "Carlos Fernández", 14),

    # --- Contratos y Convenios Colectivos ---
    ("Contratos y Convenios Colectivos", "Inventariar contratos vigentes",   "Listar personal contratado, vencimiento y tipo de vínculo.",                "done",        "high",   "Juan Martínez",    -30),
    ("Contratos y Convenios Colectivos", "Identificar vencimientos próximos","Alertar sobre contratos que vencen en los próximos 90 días.",               "done",        "urgent", "Juan Martínez",    -15),
    ("Contratos y Convenios Colectivos", "Instruir renovaciones",           "Iniciar expedientes de renovación con avales de cada área.",                "in_progress", "urgent", "Juan Martínez",     6),
    ("Contratos y Convenios Colectivos", "Publicar convenio actualizado",   "Difundir internamente el nuevo texto del CCT.",                             "todo",        "medium", "Juan Martínez",    20),

    # --- Liquidación de Haberes Marzo ---
    ("Liquidación de Haberes Marzo", "Verificar novedades del mes",       "Altas, bajas, licencias, horas extra e inasistencias.",                    "done",        "urgent", "Juan Martínez",     -5),
    ("Liquidación de Haberes Marzo", "Procesar liquidación en sistema",   "Correr el proceso de cálculo en el módulo de haberes.",                     "in_progress", "urgent", "Juan Martínez",      0),
    ("Liquidación de Haberes Marzo", "Control y auditoría interna",       "Comparar montos con mes anterior y detectar desvios.",                     "todo",        "high",   "Juan Martínez",      3),
    ("Liquidación de Haberes Marzo", "Emitir recibos de sueldo",          "Generar recibos digitales PDF y notificar a cada agente.",                 "todo",        "high",   "Juan Martínez",      5),

    # --- Tramitación de Bajas y Jubilaciones ---
    ("Tramitación de Bajas y Jubilaciones", "Recepción de solicitudes",      "Registrar solicitudes de retiro, jubilación o baja voluntaria.",           "done",        "high",   "Juan Martínez",    -20),
    ("Tramitación de Bajas y Jubilaciones", "Verificar aportes y ant. lab.",  "Validar historia laboral en ANSES y sistema interno.",                    "in_progress", "high",   "Juan Martínez",     10),
    ("Tramitación de Bajas y Jubilaciones", "Confeccionar expediente",       "Armar expediente con toda la documentación requerida.",                   "todo",        "medium", "Juan Martínez",     20),
    ("Tramitación de Bajas y Jubilaciones", "Elevar a Dirección General",    "Remitir para firma y aprobación definitiva.",                             "todo",        "low",    "Juan Martínez",     30),

    # --- Actualización de Expedientes Digitales ---
    ("Actualización de Expedientes Digitales", "Inventariar documentación física","Clasificar por apellido y año de ingreso.",                              "done",        "medium", "María López",      -40),
    ("Actualización de Expedientes Digitales", "Escanear legajos príridad A",  "Personal activo: 100% digitalizado en alta resolución.",                 "in_progress", "high",   "María López",       8),
    ("Actualización de Expedientes Digitales", "Cargar en repositorio digital","Subir PDFs al sistema con índice de búsqueda.",                           "todo",        "high",   "María López",      20),
    ("Actualización de Expedientes Digitales", "Verificar integridad de archivos","Hash SHA256 por archivo + registro de validación.",                   "todo",        "medium", "María López",      30),

    # --- Registro de Licencias Especiales ---
    ("Registro de Licencias Especiales", "Definir tipologías de licencia",  "Mapear todos los tipos según convenio: maternidad, estudio, etc.",       "done",        "medium", "María López",      -10),
    ("Registro de Licencias Especiales", "Crear formulario de solicitud",   "Diseñar formulario único digital con validaciones.",                      "in_progress", "medium", "María López",        7),
    ("Registro de Licencias Especiales", "Cargar histórico en sistema",     "Registrar licencias 2024-2025 para trazabilidad.",                        "todo",        "low",    "María López",       18),
    ("Registro de Licencias Especiales", "Configurar alertas de vencimiento","Notificaciones automáticas de retorno al sistema.",                      "todo",        "low",    "María López",       28),
]


@click.command("seed-demo")
@click.option("--force", is_flag=True, default=False,
              help="Elimina los datos de demo existentes antes de sembrar.")
@with_appcontext
def seed_demo(force: bool):
    """Popula la base de datos con datos de demo para pruebas.

    Crea unidades, usuarios, proyectos y tareas de ejemplo.
    Credenciales de acceso:

    \b
    ROL          EMAIL                   CONTRASEÑA
    super_admin  super@demo.com          Demo1234!
    admin        director@demo.com       Demo1234!
    user         laura@demo.com          Demo1234!
    user         carlos@demo.com         Demo1234!
    user         maria@demo.com          Demo1234!
    user         juan@demo.com           Demo1234!
    user         ana@demo.com            Demo1234!
    """
    demo_emails = [u[1] for u in USERS_DATA]
    demo_unit_names = [u["name"] for u in UNITS_DATA]

    if force:
        click.echo("[?] Eliminando datos de demo anteriores...")
        existing_users = User.query.filter(User.email.in_(demo_emails)).all()
        for u in existing_users:
            db.session.delete(u)
        existing_units = Unit.query.filter(Unit.name.in_(demo_unit_names)).all()
        for unit in existing_units:
            db.session.delete(unit)
        db.session.commit()
        click.echo("[?] Datos anteriores eliminados.")

    # ?? 1. Unidades …………………………………………………?
    click.echo("[?] Creando unidades organizativas...")
    units: dict[str, Unit] = {}
    for ud in UNITS_DATA:
        if Unit.query.filter_by(name=ud["name"]).first():
            click.echo(f"    [SKIP] Unidad '{ud['name']}' ya existe.")
            units[ud["name"]] = Unit.query.filter_by(name=ud["name"]).first()
            continue
        unit = Unit(
            name=ud["name"],
            description=ud["description"],
            color=ud["color"],
            emoji=ud.get("emoji") or "🏛️",
        )
        db.session.add(unit)
        db.session.flush()  # get id
        units[ud["name"]] = unit
        click.echo(f"    [+] {ud['name']}")
    for ud in UNITS_DATA:
        existing_unit = units.get(ud["name"])
        if existing_unit:
            existing_unit.emoji = ud.get("emoji") or existing_unit.emoji or "🏛️"
    db.session.commit()

    # ?? 2. Usuarios …………………………………………………??
    click.echo("[?] Creando usuarios...")
    user_map: dict[str, User] = {}
    for name, email, password, role, unit_name in USERS_DATA:
        if User.query.filter_by(email=email).first():
            click.echo(f"    [SKIP] Usuario '{email}' ya existe.")
            user_map[email] = User.query.filter_by(email=email).first()
            continue
        u = User(
            name=name,
            email=email,
            role=role,
            unit_id=units[unit_name].id if unit_name else None,
        )
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        user_map[email] = u
        click.echo(f"    [+] {name} ({role}) - {email}")
    db.session.commit()

    # ?? 3. Proyectos …………………………………………………?
    click.echo("[?] Creando proyectos...")
    project_map: dict[str, Project] = {}
    for pname, pdesc, unit_name, creator_email, is_active in PROJECTS_DATA:
        if Project.query.filter_by(name=pname).first():
            click.echo(f"    [SKIP] Proyecto '{pname}' ya existe.")
            project_map[pname] = Project.query.filter_by(name=pname).first()
            continue
        p = Project(
            name=pname,
            description=pdesc,
            unit_id=units[unit_name].id,
            created_by=user_map[creator_email].id,
            is_active=is_active,
        )
        db.session.add(p)
        db.session.flush()
        project_map[pname] = p
        status_label = "activo" if is_active else "archivado"
        click.echo(f"    [+] {pname} [{status_label}]")
    db.session.commit()

    # ?? 4. Tareas ……………………………………………………?
    click.echo("[?] Creando tareas...")
    task_count = 0
    for pname, title, description, status, priority, responsible, due_offset in TASKS_DATA:
        if pname not in project_map:
            continue
        pid = project_map[pname].id
        if Task.query.filter_by(project_id=pid, title=title).first():
            continue
        t = Task(
            project_id=pid,
            title=title,
            description=description,
            status=status,
            priority=priority,
            responsible=responsible,
            due_date=_days(due_offset),
        )
        db.session.add(t)
        task_count += 1
    db.session.commit()
    click.echo(f"    [+] {task_count} tareas creadas.")

    # ?? 5. Obras ……………………………………………………?
    click.echo("[?] Creando obras...")
    works_created = 0
    for wd in WORKS_DATA:
        unit = units.get(wd["unit_name"])
        creator = user_map.get(wd["creator_email"])
        if not unit or not creator:
            continue

        exists = Work.query.filter_by(unit_id=unit.id, title=wd["title"]).first()
        if exists:
            continue

        work = Work(
            unit_id=unit.id,
            title=wd["title"],
            description=wd["description"],
            status=wd["status"],
            progress=wd["progress"],
            location=wd["location"],
            start_date=_days(wd["start_offset"]),
            end_date=_days(wd["end_offset"]),
            budget=wd["budget"],
            created_by=creator.id,
        )
        db.session.add(work)
        works_created += 1

    db.session.commit()
    click.echo(f"    [+] {works_created} obras creadas.")

    click.echo("\n" + "=" * 60)
    click.echo("  Demo data sembrado exitosamente - CivicFlow · IDL")
    click.echo("=" * 60)
    click.echo("  ROL          EMAIL                   CONTRASEÑA")
    click.echo("  super_admin  super@demo.com          Demo1234!")
    click.echo("  admin        director@demo.com       Demo1234!")
    click.echo("  user         laura@demo.com          Demo1234!")
    click.echo("  user         carlos@demo.com         Demo1234!")
    click.echo("  user         maria@demo.com          Demo1234!")
    click.echo("  user         juan@demo.com           Demo1234!")
    click.echo("  user         ana@demo.com            Demo1234!")
    click.echo("=" * 60)
