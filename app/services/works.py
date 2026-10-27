from datetime import date
from decimal import Decimal
from flask import g
from ..extensions import db
from ..models import User, Unit
from ..models.domain import Intervention, Assignment, Contract, BudgetLine, Schedule, Record, Document, Certificate, Payment, Professional
from .access import roles, EDITORS, DIRECTORS, history, check_version, work_for
from .economics import decimal, money, rate
from .errors import require, DomainError


def iso_date(value, optional=True):
    if value in (None, '') and optional:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise DomainError('Ingresá una fecha válida AAAA-MM-DD.') from None


def text(value, name, maximum=5000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= maximum, f'{name} es obligatorio (máximo {maximum} caracteres).')
    return value.strip()


def save_work(payload, work=None):
    roles(*EDITORS)
    creating=work is None
    if work:
        check_version(work, payload)
    else:
        work = Intervention(created_by=g.user.id)
        db.session.add(work)
    for name in ('name', 'description', 'locality', 'location', 'intervention_type', 'objective'):
        if name in payload:
            setattr(work, name, text(payload[name], name, 5000 if name == 'description' else 220))
    require(work.name and work.locality, 'Nombre y localidad son obligatorios.')
    for name in ('latitude', 'longitude', 'surface', 'budget'):
        if name in payload:
            if name in ('latitude', 'longitude') and payload[name] in (None, ''):
                setattr(work, name, None)
                continue
            value = decimal(payload[name], name)
            limits = (-90, 90) if name == 'latitude' else (-180, 180) if name == 'longitude' else (0, Decimal('1e15'))
            require(limits[0] <= value <= limits[1], f'{name} fuera de rango.')
            setattr(work, name, value)
    require((work.latitude is None) == (work.longitude is None), 'Ingresá ambas coordenadas o dejá ambas vacías.')
    for name in ('start_date', 'end_date'):
        if name in payload:
            setattr(work, name, iso_date(payload[name]))
    require(not work.start_date or not work.end_date or work.start_date <= work.end_date, 'La finalización debe ser posterior al inicio.')
    if 'funding' in payload:
        require(isinstance(payload['funding'], list), 'La financiación debe ser una lista.')
        funding=[]
        for entry in payload['funding']:
            require(isinstance(entry,dict),'Fuente de financiación inválida.')
            name=text(entry.get('name',entry.get('source','')),'Fuente',200)
            amount=decimal(entry.get('amount'),'Monto de financiación')
            require(amount>=0,'Financiación negativa.')
            funding.append({'name':name,'amount':str(money(amount))})
        work.funding = funding
    if 'unit_id' in payload:
        require(payload['unit_id'] is None or db.session.get(Unit, payload['unit_id']), 'Unidad no encontrada.')
        work.unit_id = payload['unit_id']
    if 'public' in payload:
        roles(*DIRECTORS)
        require(isinstance(payload['public'], bool), 'Publicación debe ser booleana.')
        work.public = payload['public']
    db.session.flush()
    if creating:
        db.session.add(Assignment(work_id=work.id,user_id=g.user.id,role=g.user.role,contact={}))
    history(work.id, 'obra', work.id, 'guardar_ficha')
    return work


def metrics(work):
    from .rectification import effective_snapshot
    approved = Certificate.query.filter_by(work_id=work.id, status='aprobado').all()
    certified = sum((decimal(effective_snapshot(c)['calculation']['payable']) for c in approved), Decimal(0))
    physical = sum((decimal(effective_snapshot(c)['calculation']['base']) for c in approved), Decimal(0))
    contract = Contract.query.filter_by(work_id=work.id, status='aprobado', kind='contractual').order_by(Contract.version.desc()).first()
    base = sum((money(l.quantity*l.unit_price) for l in BudgetLine.query.filter_by(contract_id=contract.id)), Decimal(0)) if contract else Decimal(0)
    paid = sum((p.amount for p in Payment.query.join(Certificate, Payment.certificate_id == Certificate.id).filter(Certificate.work_id == work.id, Payment.status == 'pagado')), Decimal(0))
    tasks = Record.query.filter_by(work_id=work.id, kind='tarea').all()
    overdue = sum(bool(t.due_date and t.due_date < date.today() and t.status not in ('finalizada', 'cancelada')) for t in tasks)
    schedule = Schedule.query.filter_by(work_id=work.id, status='aprobado').order_by(Schedule.version.desc()).first()
    planned = Decimal(0)
    if work.start_date and work.end_date and work.end_date > work.start_date:
        planned = min(Decimal(1), max(Decimal(0), Decimal((date.today()-work.start_date).days)/Decimal((work.end_date-work.start_date).days))) * 100
    return {'certified': str(money(certified)), 'paid': str(money(paid)), 'physical_base': str(money(physical)), 'contract_base': str(money(base)), 'physical_percent': str((physical/base*100).quantize(Decimal('.01'))) if base else '0.00', 'planned_percent': str(planned.quantize(Decimal('.01'))), 'tasks': len(tasks), 'overdue_tasks': overdue, 'schedule_version': schedule.version if schedule else None, 'formula': 'Avance físico ponderado = suma base de certificados aprobados / suma cantidad × precio contractual; certificados y pagos se muestran por separado.'}


def transition_work(work, payload):
    roles(*DIRECTORS)
    check_version(work, payload)
    previous = work.stage
    target = payload.get('stage')
    if target:
        require((previous, target) in {('proyecto', 'obra'), ('obra', 'posobra')}, 'Cambio de etapa inválido.', 409)
        if target == 'obra':
            contract = Contract.query.filter_by(work_id=work.id, status='aprobado', kind='contractual').first()
            require(contract and contract.company_id, 'La obra requiere adjudicación y rubrado contractual aprobado.', 409)
            require(Schedule.query.filter_by(work_id=work.id, kind='contractual', status='aprobado').first(), 'Falta cronograma contractual aprobado.', 409)
            work.company_id, work.start_date, work.end_date = contract.company_id, contract.start_date, contract.end_date
        else:
            require(Decimal(metrics(work)['physical_percent']) >= 100, 'El avance aprobado debe completar los rubros antes de posobra.', 409)
            require(Document.query.filter_by(work_id=work.id, kind='plano_final').filter(Document.status != 'eliminado').first(), 'Faltan planos conformes a obra.', 409)
        work.stage, work.status = target, 'en_ejecucion' if target == 'obra' else 'finalizada'
    elif 'status' in payload:
        transitions = {'planificada': {'en_preparacion', 'archivada'}, 'en_preparacion': {'observada', 'suspendida', 'archivada'}, 'en_ejecucion': {'observada', 'suspendida', 'finalizada'}, 'observada': {'en_ejecucion', 'en_preparacion', 'suspendida'}, 'suspendida': {'en_ejecucion', 'en_preparacion', 'archivada'}, 'finalizada': {'archivada'}, 'archivada': set()}
        require(payload['status'] in transitions.get(work.status, set()), 'Estado operativo no permitido.', 409)
        work.status = payload['status']
    else:
        raise DomainError('Indicá etapa o estado.')
    history(work.id, 'obra', work.id, 'transicion', previous, work.stage, {'status': work.status, 'reason': payload.get('reason', '')})


def save_contract(work, payload):
    roles(*EDITORS)
    version = (db.session.query(db.func.max(Contract.version)).filter_by(work_id=work.id).scalar() or 0) + 1
    kind = payload.get('kind', 'inicial')
    require(kind in ('inicial', 'contractual'), 'Tipo de rubrado inválido.')
    rules = payload.get('rules', {})
    rate(rules.get('iva_rate'), 'IVA contractual')
    require(rules.get('social_payment') in ('incluido', 'separado'), 'Definí criterio de pago de leyes sociales.')
    if rules.get('icc_initial') not in (None,''):
        require(decimal(rules['icc_initial']) > 0, 'ICC inicial inválido.')
    contract = Contract(work_id=work.id, version=version, kind=kind, rules=rules, company_id=payload.get('company_id'), number=payload.get('number', ''), tender_number=payload.get('tender_number', ''), dossier_number=payload.get('dossier_number', ''), procurement_type=payload.get('procurement_type', 'licitación'), bps_number=payload.get('bps_number', ''), start_date=iso_date(payload.get('start_date')), end_date=iso_date(payload.get('end_date')), reason=payload.get('reason', ''))
    db.session.add(contract)
    db.session.flush()
    lines = payload.get('lines', [])
    require(isinstance(lines, list) and 0 < len(lines) <= 1000, 'Ingresá entre 1 y 1000 rubros.')
    codes = set()
    for data in lines:
        code = text(str(data.get('code', '')), 'Código', 100)
        require(code not in codes, f'Código repetido: {code}.')
        codes.add(code)
        quantity, price = decimal(data.get('quantity')), decimal(data.get('unit_price'))
        require(quantity > 0 and price >= 0, 'Cantidad positiva y precio no negativo son obligatorios.')
        unit = text(data.get('unit', ''), 'Unidad', 40)
        require(unit in ('m2', 'm3', 'ml', 'un', 'global', 'kg', 'h', 'l', 't'), 'Unidad desconocida. Definí su equivalencia antes de importar.')
        require(data.get('kind', 'basico') in ('basico', 'imprevisto', 'ampliacion'), 'Tipo de rubro inválido.')
        db.session.add(BudgetLine(contract_id=contract.id, code=code, chapter=data.get('chapter', 'General'), description=text(data.get('description', ''), 'Descripción'), unit=unit, quantity=quantity, unit_price=price, social_rate=rate(data.get('social_rate', '0'), 'LLSS'), kind=data.get('kind', 'basico'), icc_eligible=data.get('icc_eligible', True)))
    db.session.flush()
    lines = BudgetLine.query.filter_by(contract_id=contract.id).all()
    base = sum((money(l.quantity*l.unit_price) for l in lines), Decimal(0))
    social = sum((money(l.quantity*l.unit_price*l.social_rate) for l in lines), Decimal(0))
    contract.amount = money(base*(1+decimal(rules['iva_rate'])) + (social if rules['social_payment'] == 'incluido' else 0))
    history(work.id, 'contrato', contract.id, 'crear_version', details={'version': version, 'reason': contract.reason})
    return contract


def approve_contract(work, contract):
    roles(*DIRECTORS)
    require(contract.status == 'borrador', 'Contrato ya procesado.', 409)
    if contract.kind == 'contractual':
        require(contract.company_id and contract.number and contract.start_date and contract.end_date and contract.end_date >= contract.start_date, 'Faltan empresa, número o fechas de contrato.')
        from ..models.domain import Company
        company = db.session.get(Company, contract.company_id)
        require(company and company.status == 'activa', 'Empresa no habilitada.')
        pending = Certificate.query.filter_by(work_id=work.id).filter(Certificate.status != 'aprobado').count()
        require(not pending, 'Finalizá las certificaciones pendientes antes de cambiar contrato.', 409)
        previous = Contract.query.filter_by(work_id=work.id, kind='contractual', status='aprobado').first()
        if previous:
            require(contract.reason, 'Una modificación contractual requiere motivo y autorización.')
            require(previous.company_id==contract.company_id,'La empresa adjudicataria se conserva en las revisiones de esta intervención. Una nueva contratación independiente requiere intervención/expediente propio.',409)
            new_lines = {l.code: l for l in BudgetLine.query.filter_by(contract_id=contract.id)}
            for old in BudgetLine.query.filter_by(contract_id=previous.id):
                approved_before = any(any(r['code'] == old.code and decimal(r['accumulated']) > 0 for r in c.approved_snapshot['calculation']['lines']) for c in Certificate.query.filter_by(work_id=work.id, status='aprobado'))
                if approved_before:
                    new = new_lines.get(old.code)
                    require(new and new.quantity == old.quantity and new.unit_price == old.unit_price and new.social_rate == old.social_rate, 'No se alteran rubros ya certificados; agregá una ampliación explícita.')
            previous.status = 'sustituido'
        work.company_id = contract.company_id
        Document.query.filter_by(work_id=work.id,classification='reservado',company_id=None).update({'company_id':contract.company_id})
    contract.status = 'aprobado'
    history(work.id, 'contrato', contract.id, 'aprobar', 'borrador', 'aprobado')


RECORD_INITIAL = {'tarea': 'pendiente', 'visita': 'registrada', 'observacion': 'observado', 'mantenimiento': 'pendiente', 'recepcion': 'registrada', 'incidencia': 'registrada', 'prorroga': 'pendiente', 'licitacion': 'preparacion', 'cambio': 'pendiente'}


def save_record(work, payload):
    roles(*EDITORS, 'inspector')
    kind = payload.get('kind')
    require(kind in RECORD_INITIAL, 'Tipo de registro inválido.')
    if kind in ('recepcion', 'prorroga', 'cambio'):
        roles(*DIRECTORS)
    data = payload.get('data', {})
    require(isinstance(data, dict), 'Datos de registro inválidos.')
    responsible = payload.get('responsible_id')
    if responsible:
        require(db.session.get(User, responsible) and Assignment.query.filter_by(work_id=work.id, user_id=responsible).first(), 'El responsable debe integrar el equipo de obra.')
    for document_id in data.get('document_ids', []):
        from .access import document_for
        require(document_for(document_id).work_id == work.id, 'Documento ajeno a esta obra.')
    if kind in ('visita', 'incidencia'):
        text(data.get('description', ''), 'Informe')
    if kind == 'incidencia':
        require(data.get('type') in ('lluvia', 'paro', 'feriado', 'otro'), 'Tipo de incidencia inválido.')
    if kind == 'mantenimiento':
        require(work.stage == 'posobra', 'El mantenimiento se planifica en posobra.', 409)
        require(responsible and payload.get('due_date'), 'Definí responsable y fecha del hito.')
        require(data.get('frequency') in ('unica', 'mensual', 'trimestral', 'anual', 'estacional'), 'Definí periodicidad del mantenimiento.')
    if kind == 'recepcion':
        require(work.stage == 'posobra', 'La recepción requiere posobra.', 409)
        require(data.get('type') in ('provisoria', 'definitiva') and data.get('document_ids'), 'Indicá tipo de recepción y adjuntá el acta.')
        require(iso_date(payload.get('date'),False)<=date.today(),'La recepción realizada no puede tener fecha futura.')
        require(any(document_for(i).kind=='acta_recepcion' and document_for(i).mime=='application/pdf' for i in data['document_ids']),'La recepción requiere acta PDF clasificada como acta_recepcion.')
        if data['type'] == 'provisoria':
            require(iso_date(data.get('definitive_date'), False) >= iso_date(payload.get('date'), False), 'El plazo de recepción definitiva es inválido.')
        else:
            provisional = Record.query.filter_by(work_id=work.id, kind='recepcion').all()
            require(Document.query.filter_by(work_id=work.id,kind='manual_mantenimiento').filter(Document.status.notin_(('eliminado','sustituido'))).first(), 'Falta manual de mantenimiento.',409)
            require(Record.query.filter_by(work_id=work.id,kind='mantenimiento').first(), 'Falta plan de mantenimiento estructurado.',409)
            require(any(r.data.get('type') == 'provisoria' and iso_date(r.data['definitive_date']) <= iso_date(payload.get('date'), False) for r in provisional), 'No se cumplió el plazo de recepción provisoria.', 409)
            require(not Record.query.filter_by(work_id=work.id, kind='observacion').filter(Record.status != 'cerrado').count(), 'Hay observaciones sin cerrar.', 409)
            for r in provisional:
                if r.data.get('type')=='provisoria':r.status='cumplida'
    record = Record(work_id=work.id, kind=kind, title=text(payload.get('title', ''), 'Título', 250), status=RECORD_INITIAL[kind], responsible_id=responsible, due_date=iso_date(payload.get('due_date')), date=iso_date(payload.get('date')) or date.today(), author_id=g.user.id, data={**data, 'comments': []})
    db.session.add(record)
    if kind=='recepcion' and data.get('type')=='provisoria':
        record.due_date=iso_date(data.get('definitive_date'),False)
    db.session.flush()
    history(work.id, kind, record.id, 'crear')
    return record


def transition_record(work, record, payload):
    check_version(record, payload)
    previous = record.status
    target = payload.get('status')
    comment = text(payload.get('comment', ''), 'Comentario')
    if record.kind == 'observacion':
        if g.user.role == 'empresa':
            require(previous == 'observado' and target == 'respuesta', 'Sólo podés responder observaciones pendientes.', 409)
        else:
            roles(*DIRECTORS, 'inspector')
            require((previous, target) in {('respuesta', 'en_revision'), ('respuesta', 'cerrado'), ('en_revision', 'cerrado'), ('respuesta', 'observado'), ('en_revision', 'observado')}, 'Transición de observación inválida.', 409)
    elif record.kind == 'tarea':
        roles(*EDITORS, 'inspector')
        require(g.user.role in DIRECTORS or record.responsible_id == g.user.id, 'Sólo el responsable o dirección cambia la tarea.', 403)
        transitions = {'pendiente': {'en_curso', 'cancelada'}, 'en_curso': {'bloqueada', 'en_revision', 'cancelada'}, 'bloqueada': {'en_curso', 'cancelada'}, 'en_revision': {'en_curso', 'finalizada'}, 'finalizada': set(), 'cancelada': set()}
        require(target in transitions.get(previous, set()), 'Transición Kanban inválida.', 409)
    elif record.kind == 'mantenimiento':
        roles(*DIRECTORS, 'tecnico', 'inspector')
        require((previous, target) in {('pendiente', 'realizado'), ('realizado', 'revisado'), ('realizado', 'pendiente')}, 'Transición de mantenimiento inválida.', 409)
        if target == 'revisado':
            roles('super_admin', 'admin', 'direccion_general')
        if target == 'realizado':
            require(payload.get('document_ids'), 'Adjuntá evidencia del mantenimiento realizado.')
    elif record.kind in ('prorroga', 'cambio'):
        roles('super_admin', 'admin', 'direccion_general')
        require(previous == 'pendiente' and target in ('aprobado', 'rechazado'), 'Solicitud ya procesada.', 409)
        if target == 'aprobado' and record.kind == 'prorroga':
            new_end = iso_date(record.data.get('new_end_date'), False)
            require(work.end_date and new_end > work.end_date, 'La prórroga no extiende el plazo.')
            work.end_date = new_end
            work.version += 1
        if target == 'aprobado' and record.kind == 'cambio':
            contract=Contract.query.filter_by(id=record.data.get('contract_id'),work_id=work.id,status='borrador',kind='contractual').first()
            require(contract and record.data.get('document_ids'),'Vinculá valoración contractual y documentación del cambio.')
            approve_contract(work,contract)
            if record.data.get('schedule_id'):
                schedule=Schedule.query.filter_by(id=record.data['schedule_id'],work_id=work.id,status='borrador').first()
                require(schedule and schedule.reason,'Cronograma modificado requiere motivo.')
                schedule.status='aprobado'
    elif record.kind == 'licitacion':
        roles(*DIRECTORS)
        transitions = {'preparacion': {'publicada', 'cancelada'}, 'publicada': {'evaluacion', 'cancelada'}, 'evaluacion': {'adjudicada', 'cancelada'}, 'adjudicada': set(), 'cancelada': set()}
        require(target in transitions.get(previous, set()), 'Transición de licitación inválida.', 409)
    else:
        raise DomainError('Este registro no admite cambio de estado.')
    ids = payload.get('document_ids', [])
    from .access import document_for
    require(all(document_for(i).work_id == work.id for i in ids), 'Evidencia ajena a esta obra.')
    record.data = {**record.data, 'comments': [*record.data.get('comments', []), {'actor_id': g.user.id, 'date': date.today().isoformat(), 'text': comment, 'document_ids': ids, 'status': target}]}
    record.status = target
    if record.kind=='mantenimiento' and target=='revisado' and record.data.get('frequency')!='unica':
        import calendar
        months={'mensual':1,'trimestral':3,'anual':12,'estacional':3}[record.data['frequency']]
        anchor=max(record.due_date,date.today());month=anchor.month-1+months;year=anchor.year+month//12;month=month%12+1
        due=date(year,month,min(anchor.day,calendar.monthrange(year,month)[1]))
        next_record=Record(work_id=work.id,kind='mantenimiento',title=record.title,status='pendiente',responsible_id=record.responsible_id,due_date=due,date=date.today(),author_id=g.user.id,data={**record.data,'comments':[],'previous_record_id':record.id})
        db.session.add(next_record)
    history(work.id, record.kind, record.id, 'transicion', previous, target, {'comment': comment})
