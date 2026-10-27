"""Private company registry and explicitly validated, dated representation."""
from io import BytesIO
import hashlib
import json
from flask import g, request, send_file
from ..extensions import db
from ..models import User, ActivityLog
from ..models.domain import Company, CompanyDocument, CompanyRepresentative
from ..services.access import authenticated, roles
from ..services.documents import inspect_file
from ..services.works import text, iso_date
from ..services.errors import require
from ..infrastructure.storage import get_document_storage
from .interventions import body
from . import api_bp


def company_for(company_id, lock=False):
    if g.user.role == 'empresa':
        require(g.user.company_id == company_id, 'Empresa no encontrada.', 404)
    else:
        roles('super_admin', 'admin', 'direccion_general', 'administrativo')
    query = Company.query.filter_by(id=company_id)
    company = query.with_for_update().first() if lock else query.first()
    require(company, 'Empresa no encontrada.', 404)
    return company


def audit(company_id, action, details=None):
    db.session.add(ActivityLog(user_id=g.user.id, action='empresa:'+action,
                              details=json.dumps({'entity_type': 'empresa', 'entity_id': company_id, **(details or {})})))


@api_bp.get('/company/profile')
@authenticated
def own_profile():
    require(g.user.company_id, 'Este usuario no representa una empresa.', 404)
    return profile(g.user.company_id)


@api_bp.route('/companies/<int:company_id>/profile', methods=['GET', 'PATCH'])
@authenticated
def profile(company_id):
    company = company_for(company_id, request.method == 'PATCH')
    if request.method == 'PATCH':
        data = body()
        allowed = ('email', 'phone', 'address', 'contact_name')
        require(isinstance(data.get('contact'), dict) and set(data['contact']).issubset(allowed), 'Campos de contacto inválidos.')
        company.contact = {**company.contact, **{k: str(v).strip()[:250] for k, v in data['contact'].items()}}
        audit(company_id, 'perfil_actualizado')
        db.session.commit()
    users = {u.id: u.name for u in User.query.filter_by(company_id=company_id)}
    return {'company': company.to_dict(), 'representatives': [
        {**r.to_dict(), 'name': users.get(r.user_id, 'Usuario')} for r in CompanyRepresentative.query.filter_by(company_id=company_id)],
        'documents': [d.to_dict() for d in CompanyDocument.query.filter_by(company_id=company_id).order_by(CompanyDocument.id.desc())]}


@api_bp.post('/companies/<int:company_id>/documents')
@authenticated
def upload_company_document(company_id):
    company_for(company_id, True)
    file = request.files.get('file')
    require(file and file.filename, 'Adjuntá un archivo.')
    binary = file.read(20*1024*1024+1)
    mime, _ = inspect_file(binary, file.filename)
    kind = request.form.get('kind', 'registro')
    require(kind in ('registro', 'representacion', 'bps', 'dgi', 'otro'), 'Tipo documental inválido.')
    previous = None
    if request.form.get('previous_id'):
        previous = CompanyDocument.query.filter_by(id=int(request.form['previous_id']), company_id=company_id).first()
        require(previous and previous.status != 'sustituido', 'La versión anterior cambió.', 409)
    key, digest = get_document_storage().put(binary)
    row = CompanyDocument(company_id=company_id, name=file.filename[:250], kind=kind, author_id=g.user.id,
                          storage_key=key, sha256=digest, mime=mime, size=len(binary))
    if previous:
        row.group_id, row.version = previous.group_id, previous.version+1
        previous.status = 'sustituido'
    db.session.add(row)
    audit(company_id, 'documento_cargado', {'hash': digest})
    db.session.commit()
    return {'document': row.to_dict()}, 201


@api_bp.get('/companies/<int:company_id>/documents/<int:document_id>/download')
@authenticated
def download_company_document(company_id, document_id):
    company_for(company_id)
    document = CompanyDocument.query.filter_by(id=document_id, company_id=company_id).first()
    require(document, 'Documento no encontrado.', 404)
    binary = get_document_storage().read(document.storage_key)
    require(hashlib.sha256(binary).hexdigest() == document.sha256, 'Integridad del archivo inválida.', 409)
    audit(company_id, 'documento_descargado', {'document_id': document.id})
    db.session.commit()
    response = send_file(BytesIO(binary), mimetype=document.mime, download_name=document.name, as_attachment=True)
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


@api_bp.post('/companies/<int:company_id>/representatives/<int:user_id>')
@authenticated
def validate_representative(company_id, user_id):
    roles('super_admin', 'admin', 'direccion_general')
    company_for(company_id, True)
    user = db.session.get(User, user_id)
    require(user and user.company_id == company_id and user.role == 'empresa', 'Usuario de empresa no encontrado.', 404)
    data = body()
    status = data.get('status')
    require(status in ('pendiente', 'validada', 'revocada'), 'Estado de representación inválido.')
    start, end = iso_date(data.get('start_date'), False), iso_date(data.get('end_date'))
    require(not end or start <= end, 'Vigencia inválida.')
    evidence = CompanyDocument.query.filter_by(id=data.get('evidence_id'), company_id=company_id, kind='representacion').first()
    if status == 'validada':
        require(evidence and evidence.status != 'sustituido', 'Adjuntá evidencia privada de representación vigente.')
    row = CompanyRepresentative.query.filter_by(user_id=user_id).first()
    if not row:
        row = CompanyRepresentative(company_id=company_id, user_id=user_id)
        db.session.add(row)
    row.company_id, row.status, row.start_date, row.end_date = company_id, status, start, end
    row.validated_by = g.user.id if status == 'validada' else None
    row.evidence_id = evidence.id if evidence else None
    audit(company_id, 'representacion_'+status, {'user_id': user_id, 'start': str(start), 'end': str(end) if end else None})
    db.session.commit()
    return {'representative': row.to_dict()}
