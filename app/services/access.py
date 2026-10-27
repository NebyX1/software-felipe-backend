"""Identity comes from DB, never client claims. Resource scopes precede retrieval."""
from functools import wraps
from datetime import date
from flask import g, current_app
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from sqlalchemy import or_
from ..extensions import db
from ..models import User
from ..models.domain import Intervention, Assignment, Document, Company, History, Notification, CompanyRepresentative
from .errors import require

GLOBAL_ROLES = {'super_admin', 'admin', 'direccion_general', 'administrativo', 'consulta'}
EDITORS = {'super_admin', 'admin', 'direccion_general', 'director_obra', 'tecnico'}
DIRECTORS = {'super_admin', 'admin', 'direccion_general', 'director_obra'}


def authenticated(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        verify_jwt_in_request()
        user = db.session.get(User, int(get_jwt_identity()))
        require(user and user.is_active and (not user.demo or current_app.config['DEMO_AUTH_ENABLED']), 'Sesión no disponible.', 401, 'unauthorized')
        g.user = user
        if user.company_id:
            company = db.session.get(Company, user.company_id)
            require(company, 'Empresa no disponible.', 403)
        return fn(*args, **kwargs)
    return wrapped


def roles(*allowed):
    require(g.user.role in allowed, 'No tenés permisos para esta acción.', 403, 'forbidden')


def work_query(user=None):
    user = user or g.user
    query = Intervention.query
    if user.role == 'empresa':
        representation_for(user)
        return query.filter(Intervention.company_id == user.company_id)
    if user.role not in GLOBAL_ROLES:
        assigned = db.select(Assignment.work_id).where(Assignment.user_id == user.id)
        return query.filter(or_(Intervention.id.in_(assigned), Intervention.created_by == user.id))
    return query


def representation_for(user):
    company = db.session.get(Company, user.company_id)
    require(company and company.status == 'activa', 'La empresa no está activa.', 403)
    row = CompanyRepresentative.query.filter_by(user_id=user.id, company_id=user.company_id, status='validada').first()
    require(row and row.start_date <= date.today() and (not row.end_date or row.end_date >= date.today()),
            'La representación empresarial requiere validación y vigencia.', 403, 'representation_required')
    return row


def work_for(work_id, lock=False):
    query = work_query().filter(Intervention.id == work_id)
    work = query.with_for_update().first() if lock else query.first()
    require(work, 'Obra no encontrada.', 404, 'not_found')
    return work


def documents_query(work_id, user=None):
    user = user or g.user
    query = Document.query.filter_by(work_id=work_id).filter(Document.status != 'eliminado')
    if user.role == 'empresa':
        return query.filter(Document.classification.in_(('publico', 'reservado'))).filter(or_(Document.company_id == user.company_id, Document.classification == 'publico'))
    if user.role not in {'super_admin', 'admin', 'direccion_general'}:
        query = query.filter(Document.classification != 'confidencial')
    return query


def document_for(document_id):
    document = db.session.get(Document, document_id)
    require(document, 'Documento no encontrado.', 404)
    work_for(document.work_id)
    require(documents_query(document.work_id).filter_by(id=document_id).first(), 'Documento no encontrado.', 404)
    return document


def check_version(entity, payload):
    require(payload.get('version') == entity.version, 'El registro cambió. Recargá antes de guardar.', 409, 'version_conflict')
    entity.version += 1


def history(work_id, resource, entity_id, action, previous=None, target=None, details=None):
    event = History(work_id=work_id, resource=resource, resource_id=entity_id, actor_id=g.user.id, action=action, previous=previous, target=target, details=details or {})
    db.session.add(event)
    record_resources = ('tarea', 'visita', 'observacion', 'incidencia', 'mantenimiento', 'recepcion')
    if resource not in ('certificado', 'pago', 'tramite', 'registro', *record_resources) or action in ('descargar', 'guardar'):
        return
    db.session.flush()
    work = db.session.get(Intervention, work_id)
    assigned = {a.user_id for a in Assignment.query.filter_by(work_id=work_id) if a.user_id}
    for user in User.query.filter_by(is_active=True).filter(User.id != g.user.id):
        if user.role == 'empresa':
            if user.company_id != work.company_id:
                continue
            if resource in record_resources and resource not in ('observacion', 'incidencia'):
                continue
            # Generic event descriptions do not disclose private procedure content.
            if resource == 'tramite':
                from ..models.domain import Procedure
                if db.session.get(Procedure, entity_id).company_id != user.company_id:
                    continue
        elif user.role not in GLOBAL_ROLES and user.id not in assigned and user.id != work.created_by:
            continue
        db.session.add(Notification(user_id=user.id, work_id=work_id, event_key=f'history:{event.id}',
                                    title=f'{resource.capitalize()} · {action.replace("_", " ")} · {(target or "actualizado").replace("_", " ")}',
                                    resource='registro' if resource in record_resources else resource, resource_id=entity_id))
