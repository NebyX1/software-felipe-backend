"""Scoped inbox, documentary procedures, persistent notices and demo payments."""
from datetime import date, timedelta
from flask import g, request
from ..extensions import db
from ..models import User, Unit
from ..models.domain import (Intervention, Certificate, Payment, PaymentAttempt, Procedure,
                            Notification, Record, Contract, BudgetLine, CheckoutSession, now)
from ..services.access import authenticated, work_for, work_query, document_for, roles, history, check_version
from ..services.works import text, iso_date
from ..services.errors import require
from .interventions import body
from . import api_bp
from flask import current_app

REVIEWERS = ('super_admin', 'admin', 'direccion_general', 'director_obra', 'administrativo')


@api_bp.get('/demo/scenarios')
@authenticated
def scenarios():
    if not current_app.config['DEMO_ENVIRONMENT']:
        return {'works': []}
    from ..ai.provider import _config, ProviderUnavailable
    try:
        _config()
        assistant_available = True
    except ProviderUnavailable:
        assistant_available = False
    return {'works': [w.to_dict() for w in work_query().filter(Intervention.demo.is_(True), Intervention.code.like('DEMO-%')).order_by(Intervention.code)],
            'assistant_available': assistant_available}


@api_bp.get('/demo/materials/<name>')
@authenticated
def demo_material(name):
    from io import BytesIO
    from flask import send_file
    require(current_app.config['DEMO_ENVIRONMENT'] and g.user.demo, 'Archivos de práctica no disponibles.', 404)
    if name == 'rubrado.xlsx':
        from openpyxl import Workbook
        book = Workbook(); sheet = book.active; sheet.title = 'Rubrado de prueba'
        sheet.append(['codigo', 'descripcion', 'unidad', 'cantidad', 'precio_unitario', 'leyes_sociales', 'avance'])
        sheet.append(['DEMO-01', 'Pavimento de prueba', 'm2', 100, 500, 0.12, 25])
        sheet.append(['DEMO-02', 'Terminación de prueba', 'un', 10, 1000, 0.12, 25])
        for column in ('A', 'B', 'C', 'D', 'E', 'F', 'G'):
            sheet.column_dimensions[column].width = 30 if column == 'B' else 20
        binary = BytesIO(); book.save(binary); binary.seek(0)
        return send_file(binary, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name='rubrado-demo.xlsx')
    require(name == 'factura.pdf', 'Archivo de práctica no encontrado.', 404)
    from ..services.reports import pdf_report
    binary = pdf_report('FACTURA FICTICIA - DEMO', [
        'Documento de práctica sin validez fiscal ni comercial.', 'Empresa de ejemplo; no identifica a un proveedor real.',
        'Número: DEMO-FACTURA-001', 'Concepto: certificación de trabajos ficticios.',
        'Importe ilustrativo: UYU 305000.00. No acredita deuda ni pago real.'])
    return send_file(BytesIO(binary), mimetype='application/pdf', as_attachment=True, download_name='factura-demo.pdf')


def payment_for(work_id, payment_id):
    payment = Payment.query.join(Certificate, Certificate.id == Payment.certificate_id).filter(
        Certificate.work_id == work_id, Payment.id == payment_id).with_for_update().first()
    require(payment, 'Expediente no encontrado.', 404)
    return payment


@api_bp.get('/payments')
@authenticated
def payment_inbox():
    rows = db.session.query(Payment, Certificate, Intervention).join(
        Certificate, Certificate.id == Payment.certificate_id).join(
        Intervention, Intervention.id == Certificate.work_id).filter(
        Intervention.id.in_(work_query().with_entities(Intervention.id))).order_by(Payment.created_at.desc()).all()
    return {'payments': [{**p.to_dict(), 'work_id': w.id, 'work_name': w.name, 'work_code': w.code,
                          'period': c.period, 'company_id': w.company_id} for p, c, w in rows]}


@api_bp.route('/works/<int:work_id>/payments/<int:payment_id>/attempts', methods=['GET', 'POST'])
@authenticated
def payment_attempts(work_id, payment_id):
    work = work_for(work_id, request.method == 'POST')
    payment = payment_for(work_id, payment_id)
    if request.method == 'GET':
        return {'attempts': [a.to_dict() for a in PaymentAttempt.query.filter_by(payment_id=payment.id).order_by(PaymentAttempt.id.desc())]}
    from ..services.payment_simulator import initiate
    attempt, created = initiate(work, payment, body())
    db.session.commit()
    return {'attempt': attempt.to_dict(), 'payment': payment.to_dict()}, 201 if created else 200


@api_bp.post('/works/<int:work_id>/payments/<int:payment_id>/attempts/<int:attempt_id>/resolve')
@authenticated
def payment_response(work_id, payment_id, attempt_id):
    work = work_for(work_id, True)
    payment = payment_for(work_id, payment_id)
    attempt = PaymentAttempt.query.filter_by(payment_id=payment.id, id=attempt_id).with_for_update().first()
    require(attempt, 'Transferencia no encontrada.', 404)
    require(not CheckoutSession.query.filter_by(attempt_id=attempt.id).first(),
            'La pasarela procesa automáticamente esta operación.', 409)
    from ..services.payment_simulator import resolve
    resolve(work, payment, attempt, body())
    db.session.commit()
    return {'attempt': attempt.to_dict(), 'payment': payment.to_dict()}


def procedure_query(work_id=None):
    query = Procedure.query.filter(Procedure.work_id.in_(work_query().with_entities(Intervention.id)))
    if work_id:
        query = query.filter_by(work_id=work_id)
    if g.user.role == 'empresa':
        query = query.filter_by(company_id=g.user.company_id)
    return query


@api_bp.route('/works/<int:work_id>/procedures', methods=['GET', 'POST'])
@authenticated
def procedures(work_id):
    work = work_for(work_id, request.method == 'POST')
    if request.method == 'GET':
        return {'procedures': [p.to_dict() for p in procedure_query(work_id).order_by(Procedure.id.desc())]}
    roles(*REVIEWERS, 'empresa', 'tecnico', 'inspector')
    data = body()
    ids = evidence(work_id, data.get('document_ids', []))
    procedure = Procedure(work_id=work_id, title=text(data.get('title'), 'Asunto', 250), author_id=g.user.id,
                          company_id=g.user.company_id if g.user.role == 'empresa' else None,
                          unit_id=work.unit_id, due_date=iso_date(data.get('due_date')),
                          data={'description': text(data.get('description'), 'Solicitud'), 'document_ids': ids, 'comments': []})
    db.session.add(procedure)
    db.session.flush()
    history(work_id, 'tramite', procedure.id, 'crear', target='borrador')
    db.session.commit()
    return {'procedure': procedure.to_dict()}, 201


def evidence(work_id, ids):
    require(isinstance(ids, list) and len(ids) <= 50 and all(isinstance(i, int) for i in ids), 'Lista de adjuntos inválida.')
    require(all(document_for(i).work_id == work_id for i in ids), 'Los documentos deben pertenecer a esta intervención.')
    return ids


@api_bp.post('/works/<int:work_id>/procedures/<int:procedure_id>/transition')
@authenticated
def procedure_step(work_id, procedure_id):
    work_for(work_id, True)
    procedure = procedure_query(work_id).filter_by(id=procedure_id).with_for_update().first()
    require(procedure, 'Trámite no encontrado.', 404)
    data = body()
    check_version(procedure, data)
    target, previous = data.get('status'), procedure.status
    require(isinstance(target, str), 'Actuación inválida.')
    comment = text(data.get('comment'), 'Actuación')
    ids = evidence(work_id, data.get('document_ids', []))
    submitter = g.user.id == procedure.author_id or (g.user.role == 'empresa' and g.user.company_id == procedure.company_id)
    submit_steps = {('borrador', 'ingresado'), ('observado', 'subsanado'), ('subsanado', 'ingresado')}
    review_steps = {('ingresado', 'en_revision'), ('en_revision', 'observado'), ('en_revision', 'aprobado'),
                    ('en_revision', 'rechazado'), ('aprobado', 'archivado'), ('rechazado', 'archivado')}
    if target == 'derivar':
        roles(*REVIEWERS)
        require(previous in ('ingresado', 'en_revision', 'subsanado'), 'Este trámite ya está cerrado.', 409)
        unit = db.session.get(Unit, data.get('unit_id'))
        responsible = db.session.get(User, data.get('responsible_id'))
        require(unit and responsible and responsible.is_active and responsible.unit_id == unit.id
                and responsible.role in REVIEWERS, 'Seleccioná unidad y responsable revisor de esa unidad.')
        require(work_query(responsible).filter_by(id=work_id).first(), 'El responsable debe tener acceso a la intervención.')
        procedure.unit_id, procedure.responsible_id = unit.id, responsible.id
        procedure.due_date = iso_date(data.get('due_date'))
        target = previous
    elif (previous, target) in submit_steps:
        require(submitter, 'Sólo el solicitante puede presentar o subsanar.', 403)
        if target == 'ingresado':
            require(ids or procedure.data.get('document_ids'), 'Adjuntá la documentación a revisar.')
    else:
        roles(*REVIEWERS)
        require((previous, target) in review_steps, 'El circuito no permite ese paso.', 409)
        require(g.user.role in ('admin', 'super_admin', 'direccion_general') or not procedure.responsible_id
                or procedure.responsible_id == g.user.id, 'El trámite tiene otro responsable asignado.', 403)
    procedure.status = target
    procedure.data = {**procedure.data, 'document_ids': sorted(set(procedure.data.get('document_ids', []) + ids)),
                      'comments': [*procedure.data.get('comments', []), {'actor_id': g.user.id, 'text': comment,
                                   'date': now().isoformat(), 'status': data.get('status'), 'document_ids': ids}]}
    history(work_id, 'tramite', procedure.id, data.get('status'), previous, target,
            {'comment': comment, 'unit_id': procedure.unit_id, 'responsible_id': procedure.responsible_id})
    db.session.commit()
    return {'procedure': procedure.to_dict()}


@api_bp.get('/inbox')
@authenticated
def inbox():
    visible = work_query().with_entities(Intervention.id)
    work_names = {w.id: w.name for w in work_query()}
    procedures = [{**p.to_dict(), 'work_name': work_names[p.work_id]} for p in procedure_query().order_by(Procedure.id.desc())]
    records = Record.query.filter(Record.work_id.in_(visible), Record.status.notin_(('finalizada', 'cancelada', 'cerrada')))
    if g.user.role == 'empresa':
        records = records.filter(Record.kind.in_(('observacion', 'incidencia')))
    return {'procedures': procedures, 'records': [{**r.to_dict(), 'work_name': work_names[r.work_id]} for r in records.order_by(Record.due_date)],
            'certificates': [{**c.to_dict(), 'work_name': work_names[c.work_id]} for c in Certificate.query.filter(
                Certificate.work_id.in_(visible), Certificate.status != 'aprobado')]}


@api_bp.get('/notifications')
@authenticated
def notices():
    # Generate due notices idempotently, and re-check scope on every read.
    visible = work_query().with_entities(Intervention.id)
    from sqlalchemy.dialects.mysql import insert
    for record in Record.query.filter(Record.work_id.in_(visible), Record.responsible_id == g.user.id,
                                      Record.due_date <= date.today()+timedelta(days=7),
                                      Record.status.notin_(('finalizada', 'cancelada', 'cerrada'))):
        key = f'due:record:{record.id}:{record.due_date}'
        db.session.execute(insert(Notification).values(user_id=g.user.id, work_id=record.work_id, event_key=key,
                           title=f'Compromiso próximo o vencido · {record.due_date}', resource='registro', resource_id=record.id,
                           created_at=now()).prefix_with('IGNORE'))
    for procedure in procedure_query().filter(db.or_(Procedure.responsible_id == g.user.id, Procedure.author_id == g.user.id),
                                             Procedure.due_date <= date.today()+timedelta(days=7),
                                             Procedure.status.notin_(('aprobado','rechazado','archivado'))):
        key = f'due:procedure:{procedure.id}:{procedure.due_date}'
        db.session.execute(insert(Notification).values(user_id=g.user.id, work_id=procedure.work_id, event_key=key,
                           title=f'Plazo de trámite próximo o vencido · {procedure.due_date}', resource='tramite',
                           resource_id=procedure.id, created_at=now()).prefix_with('IGNORE'))
    db.session.commit()
    # Scope/expiry in SQL so unread counts remain accurate beyond the first page.
    query = Notification.query.filter_by(user_id=g.user.id).filter(Notification.work_id.in_(visible))
    query = query.filter(db.or_(Notification.resource != 'tramite', Notification.resource_id.in_(procedure_query().with_entities(Procedure.id))))
    active_record = db.exists().where(Record.id == Notification.resource_id, Record.responsible_id == g.user.id,
        Record.status.notin_(('finalizada','cancelada','cerrada')),
        Notification.event_key == db.func.concat('due:record:',Record.id,':',Record.due_date))
    active_procedure = db.exists().where(Procedure.id == Notification.resource_id,
        db.or_(Procedure.responsible_id == g.user.id, Procedure.author_id == g.user.id),
        Procedure.status.notin_(('aprobado','rechazado','archivado')),
        Notification.event_key == db.func.concat('due:procedure:',Procedure.id,':',Procedure.due_date))
    query = query.filter(db.or_(~Notification.event_key.like('due:record:%'),active_record),
                         db.or_(~Notification.event_key.like('due:procedure:%'),active_procedure))
    page = max(1, request.args.get('page',1,type=int))
    rows = query.order_by(Notification.id.desc()).paginate(page=page,per_page=50,error_out=False)
    return {'notifications':[n.to_dict() for n in rows.items], 'unread':query.filter(Notification.read_at.is_(None)).count(),
            'page':rows.page,'pages':rows.pages,'total':rows.total}


@api_bp.post('/notifications/<int:notice_id>/read')
@authenticated
def read_notice(notice_id):
    notice = Notification.query.filter_by(user_id=g.user.id, id=notice_id).first()
    require(notice, 'Aviso no encontrado.', 404)
    work_for(notice.work_id)
    notice.read_at = notice.read_at or now()
    db.session.commit()
    return {'notification': notice.to_dict()}


@api_bp.get('/catalog/historic-prices')
@authenticated
def historic_prices():
    roles(*REVIEWERS, 'tecnico', 'inspector', 'consulta')
    rows = db.session.query(BudgetLine, Contract, Intervention).join(Contract, BudgetLine.contract_id == Contract.id).join(
        Intervention, Contract.work_id == Intervention.id).filter(Contract.status == 'aprobado',
        Intervention.id.in_(work_query().with_entities(Intervention.id))).order_by(Contract.created_at.desc()).limit(1000)
    return {'prices': [{**line.to_dict(), 'work_id': work.id, 'work_name': work.name, 'locality': work.locality,
                       'source': f'Contrato {contract.number} · versión {contract.version}',
                       'date': (contract.start_date or contract.created_at.date()).isoformat(),
                       'contract_kind': contract.kind, 'demo': work.demo} for line, contract, work in rows]}
