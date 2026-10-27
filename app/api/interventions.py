from datetime import date
from decimal import Decimal
from flask import request, g
from ..extensions import db
from ..models import User
from ..models.domain import Intervention, Assignment, Contract, BudgetLine, Record, Schedule, History, Professional
from ..services.access import authenticated, work_query, work_for, roles, EDITORS, DIRECTORS, history
from ..services.works import save_work, transition_work, metrics, save_contract, approve_contract, save_record, transition_record, iso_date, text
from ..services.errors import require
from . import api_bp


def body():
    data = request.get_json(silent=True)
    require(isinstance(data, dict), 'Se requiere un objeto JSON.')
    return data


def filtered(query):
    start_year=request.args.get('year_from',type=int);end_year=request.args.get('year_to',type=int)
    require((start_year is None or 1900<=start_year<=2200) and (end_year is None or 1900<=end_year<=2200),'Año fuera de rango.')
    if start_year:query=query.filter(Intervention.end_date>=date(start_year,1,1))
    if end_year:query=query.filter(Intervention.start_date<=date(end_year,12,31))
    for name in ('stage', 'status', 'locality', 'objective'):
        value = request.args.get(name)
        if value:
            query = query.filter(getattr(Intervention, name) == value)
    if request.args.get('q'):
        query = query.filter(Intervention.name.contains(request.args['q'][:200], autoescape=True))
    if request.args.get('responsible_id', type=int):
        query = query.filter(Intervention.id.in_(db.select(Assignment.work_id).where(Assignment.user_id == request.args.get('responsible_id', type=int))))
    return query


@api_bp.get('/works')
@authenticated
def works():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, max(1, request.args.get('per_page', 20, type=int)))
    sort = request.args.get('sort', 'created_at')
    require(sort in ('name', 'budget', 'start_date', 'created_at'), 'Orden inválido.')
    query = filtered(work_query()).order_by(getattr(Intervention, sort).desc(), Intervention.id)
    rows = query.paginate(page=page, per_page=per_page, error_out=False)
    return {'works': [{**w.to_dict(), 'metrics': metrics(w)} for w in rows.items], 'total': rows.total, 'page': page, 'pages': rows.pages}


@api_bp.post('/works')
@authenticated
def create_work():
    work = save_work(body())
    db.session.commit()
    return {'work': work.to_dict()}, 201


@api_bp.get('/works/map')
@authenticated
def map_works():
    return {'works':[w.to_dict() for w in filtered(work_query()).order_by(Intervention.id)]}


@api_bp.get('/works/<int:work_id>')
@authenticated
def detail(work_id):
    work = work_for(work_id)
    actors = []
    for assignment in Assignment.query.filter_by(work_id=work.id):
        user = db.session.get(User, assignment.user_id) if assignment.user_id else None
        professional = db.session.get(Professional, assignment.professional_id) if assignment.professional_id else None
        actors.append({**assignment.to_dict(), 'name': user.name if user else professional.name if professional else 'Asesor', 'contact': assignment.contact if g.user.role != 'empresa' else {}})
    return {'work': work.to_dict(), 'metrics': metrics(work), 'actors': actors}


@api_bp.patch('/works/<int:work_id>')
@authenticated
def update_work(work_id):
    work = save_work(body(), work_for(work_id, True))
    db.session.commit()
    return {'work': work.to_dict()}


@api_bp.post('/works/<int:work_id>/transition')
@authenticated
def change_stage(work_id):
    work = work_for(work_id, True)
    transition_work(work, body())
    db.session.commit()
    return {'work': work.to_dict()}


@api_bp.post('/works/<int:work_id>/actors')
@authenticated
def assign_actor(work_id):
    work = work_for(work_id, True)
    roles(*DIRECTORS)
    data = body()
    user_id, professional_id = data.get('user_id'), data.get('professional_id')
    require(bool(user_id) != bool(professional_id), 'Seleccioná usuario o profesional.')
    if user_id:
        user = db.session.get(User, user_id)
        require(user and user.is_active and user.role != 'empresa', 'Usuario interno no disponible.')
    if professional_id:
        require(db.session.get(Professional, professional_id), 'Profesional no encontrado.')
    actor = Assignment.query.filter_by(work_id=work_id, user_id=user_id).first() if user_id else None
    actor = actor or Assignment(work_id=work_id, user_id=user_id, professional_id=professional_id)
    actor.role, actor.contact = text(data.get('role', ''), 'Rol', 100), data.get('contact', {})
    db.session.add(actor)
    db.session.flush()
    history(work_id, 'actor', actor.id, 'asignar')
    db.session.commit()
    return {'actor': actor.to_dict()}, 201


@api_bp.delete('/works/<int:work_id>/actors/<int:actor_id>')
@authenticated
def remove_actor(work_id, actor_id):
    work_for(work_id, True)
    roles(*DIRECTORS)
    actor = Assignment.query.filter_by(work_id=work_id, id=actor_id).first()
    require(actor, 'Asignación no encontrada.', 404)
    history(work_id, 'actor', actor.id, 'retirar')
    db.session.delete(actor)
    db.session.commit()
    return {'ok': True}


@api_bp.route('/works/<int:work_id>/contracts', methods=['GET', 'POST'])
@authenticated
def contracts(work_id):
    work = work_for(work_id, request.method == 'POST')
    if request.method == 'POST':
        contract = save_contract(work, body())
        db.session.commit()
        return {'contract': contract.to_dict()}, 201
    return {'contracts': [{**c.to_dict(), 'lines': [l.to_dict() for l in BudgetLine.query.filter_by(contract_id=c.id)]} for c in Contract.query.filter_by(work_id=work_id).order_by(Contract.version.desc())]}


@api_bp.post('/works/<int:work_id>/contracts/<int:contract_id>/approve')
@authenticated
def contract_approve(work_id, contract_id):
    work = work_for(work_id, True)
    contract = Contract.query.filter_by(id=contract_id, work_id=work_id).first()
    require(contract, 'Contrato no encontrado.', 404)
    approve_contract(work, contract)
    db.session.commit()
    return {'contract': contract.to_dict()}


@api_bp.route('/works/<int:work_id>/schedules', methods=['GET', 'POST'])
@authenticated
def schedules(work_id):
    work_for(work_id, request.method == 'POST')
    if request.method == 'GET':
        return {'schedules': [s.to_dict() for s in Schedule.query.filter_by(work_id=work_id).order_by(Schedule.version.desc())]}
    roles(*EDITORS)
    data = body()
    require(data.get('kind') in ('inicial', 'contractual'), 'Tipo de cronograma inválido.')
    activities = data.get('activities')
    require(isinstance(activities, list) and 0 < len(activities) <= 500, 'Ingresá actividades del cronograma.')
    for activity in activities:
        text(activity.get('title', ''), 'Actividad', 250)
        require(iso_date(activity.get('end'), False) >= iso_date(activity.get('start'), False), 'Fechas de actividad inválidas.')
        require(Assignment.query.filter_by(work_id=work_id, user_id=activity.get('responsible_id')).first(), 'Responsable del cronograma debe integrar el equipo.')
    version = (db.session.query(db.func.max(Schedule.version)).filter_by(work_id=work_id).scalar() or 0)+1
    schedule = Schedule(work_id=work_id, version=version, kind=data['kind'], activities=activities, reason=data.get('reason', ''))
    db.session.add(schedule)
    db.session.flush()
    history(work_id, 'cronograma', schedule.id, 'crear_version')
    db.session.commit()
    return {'schedule': schedule.to_dict()}, 201


@api_bp.post('/works/<int:work_id>/schedules/<int:schedule_id>/approve')
@authenticated
def schedule_approve(work_id, schedule_id):
    work_for(work_id, True)
    roles(*DIRECTORS)
    schedule = Schedule.query.filter_by(work_id=work_id, id=schedule_id).first()
    require(schedule and schedule.status == 'borrador', 'Cronograma no disponible.', 409)
    require(schedule.version == 1 or schedule.reason, 'Un cambio de línea base requiere motivo.')
    schedule.status = 'aprobado'
    history(work_id, 'cronograma', schedule.id, 'aprobar')
    db.session.commit()
    return {'schedule': schedule.to_dict()}


@api_bp.route('/works/<int:work_id>/records', methods=['GET', 'POST'])
@authenticated
def records(work_id):
    work = work_for(work_id, request.method == 'POST')
    if request.method == 'POST':
        record = save_record(work, body())
        db.session.commit()
        return {'record': record.to_dict()}, 201
    query = Record.query.filter_by(work_id=work_id)
    if request.args.get('kind'):
        query = query.filter_by(kind=request.args['kind'])
    if g.user.role == 'empresa':
        query = query.filter(Record.kind.in_(('observacion', 'recepcion', 'cambio', 'visita')))
    return {'records': [r.to_dict() for r in query.order_by(Record.created_at.desc())]}


@api_bp.post('/works/<int:work_id>/records/<int:record_id>/transition')
@authenticated
def record_transition(work_id, record_id):
    work = work_for(work_id, True)
    record = Record.query.filter_by(work_id=work_id, id=record_id).with_for_update().first()
    require(record, 'Registro no encontrado.', 404)
    transition_record(work, record, body())
    db.session.commit()
    return {'record': record.to_dict()}


@api_bp.patch('/works/<int:work_id>/records/<int:record_id>')
@authenticated
def edit_record(work_id,record_id):
    work_for(work_id,True);roles(*EDITORS,'inspector')
    record=Record.query.filter_by(work_id=work_id,id=record_id).with_for_update().first()
    require(record,'Registro no encontrado.',404)
    require(record.kind not in ('recepcion','cambio','prorroga') and record.status not in ('cerrado','revisado','finalizada','cancelada'),'Registro cerrado: conservá su actuación y creá un nuevo registro.',409)
    from ..services.access import check_version
    data=body();check_version(record,data)
    if 'title' in data:record.title=text(data['title'],'Título',250)
    if 'responsible_id' in data:
        require(not data['responsible_id'] or Assignment.query.filter_by(work_id=work_id,user_id=data['responsible_id']).first(),'Responsable fuera del equipo.')
        record.responsible_id=data['responsible_id']
    if 'due_date' in data:record.due_date=iso_date(data['due_date'])
    if 'data' in data:
        require(isinstance(data['data'],dict),'Informe inválido.')
        changes={key:data['data'][key] for key in ('description','priority','frequency') if key in data['data']}
        if record.kind=='mantenimiento':
            require(record.responsible_id and record.due_date and changes.get('frequency',record.data.get('frequency')) in ('unica','mensual','trimestral','anual','estacional'),'Mantenimiento requiere responsable, fecha y periodicidad.')
        record.data={**record.data,**changes}
    history(work_id,record.kind,record.id,'editar_planificacion',details={'version':record.version})
    db.session.commit();return {'record':record.to_dict()}


@api_bp.get('/works/<int:work_id>/history')
@authenticated
def work_history(work_id):
    work_for(work_id)
    query = History.query.filter_by(work_id=work_id)
    if g.user.role == 'empresa':
        query = query.filter(History.resource.in_(('certificado', 'pago', 'observacion', 'recepcion', 'contrato')))
    return {'history': [h.to_dict() for h in query.order_by(History.id.desc()).limit(500)]}


@api_bp.get('/dashboard')
@authenticated
def dashboard():
    rows = filtered(work_query()).all()
    indicators = [metrics(w) for w in rows]
    funding={}
    for w in rows:
        for entry in w.funding:
            name=str(entry.get('name') or entry.get('source') or 'Sin fuente')
            from ..services.economics import decimal
            funding[name]=funding.get(name,Decimal(0))+decimal(entry.get('amount','0'))
    years={}
    for w in rows:
        year=str(w.start_date.year) if w.start_date else 'Sin fecha'
        years.setdefault(year,{'count':0,'budget':Decimal(0)})
        years[year]['count']+=1;years[year]['budget']+=w.budget
    return {'count': len(rows), 'surface': str(sum((w.surface for w in rows), Decimal(0))), 'budget': str(sum((w.budget for w in rows), Decimal(0))), 'certified': str(sum((Decimal(m['certified']) for m in indicators), Decimal(0))), 'paid': str(sum((Decimal(m['paid']) for m in indicators), Decimal(0))), 'stages': {stage: sum(w.stage == stage for w in rows) for stage in ('proyecto', 'obra', 'posobra')}, 'funding':[{'name':k,'amount':str(v)} for k,v in funding.items()],'years':{k:{'count':v['count'],'budget':str(v['budget'])} for k,v in years.items()}, 'alerts': [{'work_id': r.work_id, 'id': r.id, 'title': r.title, 'due_date': r.due_date.isoformat(), 'kind': r.kind, 'overdue': r.due_date < date.today()} for r in Record.query.filter(Record.work_id.in_([w.id for w in rows]), Record.due_date <= date.fromordinal(date.today().toordinal()+30), Record.status.notin_(('finalizada', 'cancelada', 'revisado', 'cerrado', 'cumplida'))).order_by(Record.due_date) if r.due_date]}


PUBLIC_FIELDS = ('id', 'code', 'name', 'locality', 'intervention_type', 'objective', 'surface', 'stage', 'status', 'latitude', 'longitude', 'budget')


@api_bp.get('/public/works')
def public_works():
    return {'works': [{k: w.to_dict()[k] for k in PUBLIC_FIELDS} for w in filtered(Intervention.query.filter_by(public=True))]}


@api_bp.get('/public/geojson')
def geojson():
    return {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [float(w.longitude), float(w.latitude)]}, 'properties': {k: w.to_dict()[k] for k in PUBLIC_FIELDS if k not in ('latitude', 'longitude')}} for w in filtered(Intervention.query.filter_by(public=True)) if w.latitude is not None and w.longitude is not None]}
