import json
import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import request, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from werkzeug.utils import secure_filename

from . import api_bp
from ..extensions import db
from ..models import (
    Work,
    WorkDocument,
    WorkTask,
    WorkTaskDocument,
    Unit,
    ActivityLog,
)
from ..models.work import (
    WORK_STATUSES,
    WORK_DOC_KINDS,
    WORK_TASK_STATUSES,
    WORK_TASK_PRIORITIES,
)


def _is_admin_or_super(claims):
    return claims.get('role') in ('admin', 'super_admin')


def _can_access_unit(claims, unit_id: int) -> bool:
    if _is_admin_or_super(claims):
        return True
    return claims.get('unit_id') == unit_id


def _log(action, user_id, entity_id=None, details=None):
    detail_str = None
    if details or entity_id is not None:
        d = {'entity_type': 'work'}
        if entity_id is not None:
            d['entity_id'] = entity_id
        if details:
            d.update(details)
        detail_str = json.dumps(d, ensure_ascii=False)
    db.session.add(
        ActivityLog(
            user_id=user_id,
            action=action,
            details=detail_str,
            ip_address=request.remote_addr,
        )
    )


def _parse_iso_date(value):
    if value in (None, ''):
        return None
    return datetime.fromisoformat(value).date()


def _safe_ext(filename: str, mime: str) -> str:
    ext = os.path.splitext(filename)[1].lower().strip()
    if ext and len(ext) <= 10:
        return ext
    by_mime = {
        'application/pdf': '.pdf',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'text/plain': '.txt',
        'image/webp': '.webp',
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
    }
    return by_mime.get(mime, '.bin')


def _validate_upload(file, upload_type: str):
    if not file:
        return None, {'error': 'Debe adjuntar un archivo.'}, 400
    mime = (file.mimetype or '').lower()
    if upload_type == 'image':
        allowed = current_app.config['WORKS_ALLOWED_IMAGE_MIME_TYPES']
        if mime not in allowed:
            return None, {'error': 'Formato de imagen no permitido.'}, 400
    else:
        allowed = current_app.config['WORKS_ALLOWED_DOCUMENT_MIME_TYPES']
        if mime not in allowed:
            return None, {'error': 'Formato de documento no permitido.'}, 400
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > current_app.config['WORKS_MAX_FILE_SIZE']:
        return None, {'error': 'El archivo excede 2MB.'}, 400
    return {'mime': mime, 'size': size, 'ext': _safe_ext(file.filename or '', mime)}, None, None


def _store_uploaded_file(path_parts: list, file, ext: str, mime: str) -> str:
    root_dir = current_app.config['WORKS_UPLOAD_DIR']
    target_dir = os.path.join(root_dir, *path_parts)
    os.makedirs(target_dir, exist_ok=True)
    stored_name = f'{uuid.uuid4().hex}{ext}'
    file.save(os.path.join(target_dir, stored_name))
    return '/'.join(path_parts + [stored_name])


def _download_stored_file(stored_name: str, mime: str):
    root_dir = current_app.config['WORKS_UPLOAD_DIR']
    full_path = os.path.join(root_dir, stored_name)
    if os.path.exists(full_path):
        return send_file(full_path, mimetype=mime, as_attachment=False)
    return {'error': 'Archivo no encontrado.'}, 404


@api_bp.route('/works', methods=['GET'])
@jwt_required()
def list_works():
    claims = get_jwt()
    q = Work.query

    unit_id = request.args.get('unit_id', type=int)
    if unit_id:
        if not _can_access_unit(claims, unit_id):
            return {'error': 'No tienes acceso a esta área.'}, 403
        q = q.filter_by(unit_id=unit_id)
    elif not _is_admin_or_super(claims):
        caller_unit = claims.get('unit_id')
        if not caller_unit:
            return {'works': []}, 200
        q = q.filter_by(unit_id=caller_unit)

    status = request.args.get('status')
    if status:
        q = q.filter_by(status=status)

    works = q.order_by(Work.updated_at.desc()).all()
    return {'works': [w.to_dict() for w in works]}, 200


@api_bp.route('/works', methods=['POST'])
@jwt_required()
def create_work():
    claims = get_jwt()
    body = request.get_json(silent=True) or {}

    title = (body.get('title') or '').strip()
    if not title:
        return {'error': 'El título es requerido.'}, 400

    unit_id = body.get('unit_id')
    if unit_id is not None:
        try:
            unit_id = int(unit_id)
        except (TypeError, ValueError):
            return {'error': 'Área inválida.'}, 400

    if _is_admin_or_super(claims):
        if not unit_id:
            return {'error': 'Debe especificar el área.'}, 400
    else:
        unit_id = claims.get('unit_id')

    unit = Unit.query.get(unit_id)
    if not unit:
        return {'error': 'Área no encontrada.'}, 404

    if not _can_access_unit(claims, unit_id):
        return {'error': 'No tienes acceso a esta área.'}, 403

    status = body.get('status') or 'planning'
    if status not in WORK_STATUSES:
        return {'error': 'Estado de obra inválido.'}, 400

    progress = int(body.get('progress') or 0)
    progress = max(0, min(100, progress))

    budget_raw = body.get('budget')
    budget = None
    if budget_raw not in (None, ''):
        try:
            budget = Decimal(str(budget_raw))
        except InvalidOperation:
            return {'error': 'Presupuesto inválido.'}, 400

    work = Work(
        unit_id=unit_id,
        title=title,
        description=(body.get('description') or '').strip() or None,
        status=status,
        progress=progress,
        location=(body.get('location') or '').strip() or None,
        start_date=_parse_iso_date(body.get('start_date')),
        end_date=_parse_iso_date(body.get('end_date')),
        budget=budget,
        created_by=int(get_jwt_identity()),
    )
    db.session.add(work)
    db.session.flush()
    _log(
        'create_work',
        int(get_jwt_identity()),
        work.id,
        {'title': work.title, 'unit_id': unit_id},
    )
    db.session.commit()

    return {'work': work.to_dict()}, 201


@api_bp.route('/works/<int:wid>', methods=['PUT'])
@jwt_required()
def update_work(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)

    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    body = request.get_json(silent=True) or {}

    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return {'error': 'El título no puede estar vacío.'}, 400
        work.title = title

    if 'description' in body:
        work.description = (body.get('description') or '').strip() or None

    if 'status' in body:
        status = body.get('status')
        if status not in WORK_STATUSES:
            return {'error': 'Estado inválido.'}, 400
        work.status = status

    if 'progress' in body:
        work.progress = max(0, min(100, int(body.get('progress') or 0)))

    if 'location' in body:
        work.location = (body.get('location') or '').strip() or None

    if 'start_date' in body:
        work.start_date = _parse_iso_date(body.get('start_date'))

    if 'end_date' in body:
        work.end_date = _parse_iso_date(body.get('end_date'))

    if 'budget' in body:
        raw = body.get('budget')
        if raw in (None, ''):
            work.budget = None
        else:
            try:
                work.budget = Decimal(str(raw))
            except InvalidOperation:
                return {'error': 'Presupuesto inválido.'}, 400

    _log('update_work', int(get_jwt_identity()), work.id)
    db.session.commit()
    return {'work': work.to_dict()}, 200


@api_bp.route('/works/<int:wid>', methods=['DELETE'])
@jwt_required()
def delete_work(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)

    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    _log(
        'delete_work',
        int(get_jwt_identity()),
        work.id,
        {'title': work.title},
    )
    db.session.delete(work)
    db.session.commit()
    return {'message': 'Obra eliminada.'}, 200


@api_bp.route('/works/<int:wid>/documents', methods=['GET'])
@jwt_required()
def list_work_documents(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    docs = WorkDocument.query.filter_by(work_id=wid).order_by(
        WorkDocument.uploaded_at.desc()
    ).all()
    return {'documents': [d.to_dict() for d in docs]}, 200


@api_bp.route('/works/<int:wid>/documents', methods=['POST'])
@jwt_required()
def upload_work_document(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    kind = (request.form.get('kind') or 'other').strip()
    if kind not in WORK_DOC_KINDS:
        return {'error': 'Tipo de documento inválido.'}, 400

    upload_type = (
        (request.form.get('upload_type') or 'document')
        .strip()
        .lower()
    )
    if upload_type not in ('document', 'image'):
        return {'error': 'Tipo de carga inválido.'}, 400

    file = request.files.get('file')
    upload_data, err_body, err_code = _validate_upload(file, upload_type)
    if err_body:
        return err_body, err_code
    mime = upload_data['mime']
    size = upload_data['size']
    ext = upload_data['ext']

    original_name = secure_filename(file.filename or 'documento')
    stored_name = _store_uploaded_file(
        ['works', str(work.id), 'documents'],
        file,
        ext,
        mime,
    )

    doc = WorkDocument(
        work_id=work.id,
        kind=kind,
        original_name=original_name,
        stored_name=stored_name,
        mime_type=mime,
        size_bytes=size,
        uploaded_by=int(get_jwt_identity()),
    )
    db.session.add(doc)
    db.session.flush()

    _log(
        'upload_work_document',
        int(get_jwt_identity()),
        work.id,
        {'document_id': doc.id, 'kind': kind},
    )
    db.session.commit()

    return {'document': doc.to_dict()}, 201


@api_bp.route('/works/<int:wid>/documents/<int:doc_id>', methods=['GET'])
@jwt_required()
def download_work_document(wid, doc_id):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    doc = WorkDocument.query.filter_by(id=doc_id, work_id=wid).first_or_404()
    return _download_stored_file(doc.stored_name, doc.mime_type)


@api_bp.route('/works/<int:wid>/tasks', methods=['GET'])
@jwt_required()
def list_work_tasks(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    tasks = WorkTask.query.filter_by(work_id=wid).order_by(
        WorkTask.id.desc()
    ).all()
    return {'tasks': [t.to_dict() for t in tasks]}, 200


@api_bp.route('/works/<int:wid>/tasks', methods=['POST'])
@jwt_required()
def create_work_task(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    body = request.get_json(silent=True) or {}
    title = (body.get('title') or '').strip()
    if not title:
        return {'error': 'El titulo de la tarea es requerido.'}, 400

    status = (body.get('status') or 'todo').strip()
    if status not in WORK_TASK_STATUSES:
        return {'error': 'Estado de tarea invalido.'}, 400

    priority = (body.get('priority') or 'medium').strip()
    if priority not in WORK_TASK_PRIORITIES:
        return {'error': 'Prioridad invalida.'}, 400

    progress = int(body.get('progress') or 0)
    progress = max(0, min(100, progress))
    if status == 'done':
        progress = 100

    task = WorkTask(
        work_id=wid,
        title=title,
        description=(body.get('description') or '').strip() or None,
        status=status,
        priority=priority,
        responsible=(body.get('responsible') or '').strip() or None,
        due_date=_parse_iso_date(body.get('due_date')),
        progress=progress,
    )
    db.session.add(task)
    db.session.flush()

    _log(
        'create_work_task',
        int(get_jwt_identity()),
        wid,
        {'task_id': task.id, 'title': task.title},
    )
    db.session.commit()
    return {'task': task.to_dict()}, 201


@api_bp.route('/works/<int:wid>/tasks/<int:tid>', methods=['PUT', 'PATCH'])
@jwt_required()
def update_work_task(wid, tid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    task = WorkTask.query.filter_by(work_id=wid, id=tid).first_or_404()
    body = request.get_json(silent=True) or {}

    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return {'error': 'El titulo no puede estar vacio.'}, 400
        task.title = title

    if 'description' in body:
        task.description = (body.get('description') or '').strip() or None

    if 'status' in body:
        status = (body.get('status') or '').strip()
        if status not in WORK_TASK_STATUSES:
            return {'error': 'Estado de tarea invalido.'}, 400
        task.status = status

    if 'priority' in body:
        priority = (body.get('priority') or '').strip()
        if priority not in WORK_TASK_PRIORITIES:
            return {'error': 'Prioridad invalida.'}, 400
        task.priority = priority

    if 'responsible' in body:
        task.responsible = (body.get('responsible') or '').strip() or None

    if 'due_date' in body:
        task.due_date = _parse_iso_date(body.get('due_date'))

    if 'progress' in body:
        progress = int(body.get('progress') or 0)
        task.progress = max(0, min(100, progress))

    if task.status == 'done':
        task.progress = 100

    _log(
        'update_work_task',
        int(get_jwt_identity()),
        wid,
        {'task_id': task.id},
    )
    db.session.commit()
    return {'task': task.to_dict()}, 200


@api_bp.route('/works/<int:wid>/tasks/<int:tid>', methods=['DELETE'])
@jwt_required()
def delete_work_task(wid, tid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    task = WorkTask.query.filter_by(work_id=wid, id=tid).first_or_404()
    _log(
        'delete_work_task',
        int(get_jwt_identity()),
        wid,
        {'task_id': task.id, 'title': task.title},
    )
    db.session.delete(task)
    db.session.commit()
    return {'message': 'Tarea de obra eliminada.'}, 200


@api_bp.route('/works/<int:wid>/kpis', methods=['GET'])
@jwt_required()
def work_kpis(wid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    tasks = WorkTask.query.filter_by(work_id=wid).all()
    total = len(tasks)
    done = len([t for t in tasks if t.status == 'done'])
    completion = round((done / total) * 100, 1) if total else 0

    by_status = {
        status: len([t for t in tasks if t.status == status])
        for status in WORK_TASK_STATUSES
    }
    by_priority = {
        priority: len([t for t in tasks if t.priority == priority])
        for priority in WORK_TASK_PRIORITIES
    }
    avg_progress = (
        round(sum(t.progress for t in tasks) / total, 1) if total else 0
    )

    return {
        'kpis': {
            'total_tasks': total,
            'done_tasks': done,
            'completion_rate': completion,
            'avg_progress': avg_progress,
            'documents_count': work.documents.count(),
        },
        'by_status': by_status,
        'by_priority': by_priority,
    }, 200


@api_bp.route('/works/<int:wid>/tasks/<int:tid>/documents', methods=['GET'])
@jwt_required()
def list_work_task_documents(wid, tid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    task = WorkTask.query.filter_by(work_id=wid, id=tid).first_or_404()
    docs = WorkTaskDocument.query.filter_by(task_id=task.id).order_by(
        WorkTaskDocument.uploaded_at.desc()
    ).all()
    return {'documents': [d.to_dict() for d in docs]}, 200


@api_bp.route('/works/<int:wid>/tasks/<int:tid>/documents', methods=['POST'])
@jwt_required()
def upload_work_task_document(wid, tid):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    task = WorkTask.query.filter_by(work_id=wid, id=tid).first_or_404()
    kind = (request.form.get('kind') or 'task_attachment').strip()
    if kind not in WORK_DOC_KINDS:
        return {'error': 'Tipo de documento invalido.'}, 400

    upload_type = (
        (request.form.get('upload_type') or 'document')
        .strip()
        .lower()
    )
    if upload_type not in ('document', 'image'):
        return {'error': 'Tipo de carga inválido.'}, 400

    file = request.files.get('file')
    upload_data, err_body, err_code = _validate_upload(file, upload_type)
    if err_body:
        return err_body, err_code
    mime = upload_data['mime']
    size = upload_data['size']
    ext = upload_data['ext']

    original_name = secure_filename(file.filename or 'documento')
    stored_name = _store_uploaded_file(
        ['works', str(work.id), 'tasks', str(task.id), 'documents'],
        file,
        ext,
        mime,
    )

    doc = WorkTaskDocument(
        task_id=task.id,
        kind=kind,
        original_name=original_name,
        stored_name=stored_name,
        mime_type=mime,
        size_bytes=size,
        uploaded_by=int(get_jwt_identity()),
    )
    db.session.add(doc)
    db.session.flush()

    _log(
        'upload_work_task_document',
        int(get_jwt_identity()),
        wid,
        {'task_id': task.id, 'document_id': doc.id},
    )
    db.session.commit()
    return {'document': doc.to_dict()}, 201


@api_bp.route(
    '/works/<int:wid>/tasks/<int:tid>/documents/<int:doc_id>',
    methods=['GET'],
)
@jwt_required()
def download_work_task_document(wid, tid, doc_id):
    claims = get_jwt()
    work = Work.query.get_or_404(wid)
    if not _can_access_unit(claims, work.unit_id):
        return {'error': 'No tienes acceso a esta obra.'}, 403

    task = WorkTask.query.filter_by(work_id=wid, id=tid).first_or_404()
    doc = WorkTaskDocument.query.filter_by(
        task_id=task.id,
        id=doc_id,
    ).first_or_404()
    return _download_stored_file(doc.stored_name, doc.mime_type)
