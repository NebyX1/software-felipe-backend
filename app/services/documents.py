from io import BytesIO
from pathlib import Path
import zipfile
from PIL import Image
from pypdf import PdfReader
from flask import g
from ..extensions import db
from ..models.domain import Document, Record, Certificate, Chunk
from ..infrastructure.storage import get_document_storage
from .access import document_for, roles, history, EDITORS
from .errors import require, DomainError

MAX_SIZE = 20*1024*1024


def inspect_file(content, filename):
    require(0 < len(content) <= MAX_SIZE, 'El archivo debe tener contenido y no superar 20 MB.', 413)
    suffix = Path(filename).suffix.lower()
    try:
        if content.startswith(b'%PDF-'):
            pdf = PdfReader(BytesIO(content), strict=True)
            require(not pdf.is_encrypted and 0 < len(pdf.pages) <= 200, 'PDF cifrado o de más de 200 páginas.')
            root = pdf.trailer['/Root']
            require(not root.get('/OpenAction') and not root.get('/AA'), 'El PDF contiene acciones activas.')
            require(suffix == '.pdf', 'La extensión no corresponde al contenido PDF.')
            return 'application/pdf', len(pdf.pages)
        if suffix in ('.xlsx', '.ods'):
            with zipfile.ZipFile(BytesIO(content)) as archive:
                files = archive.infolist()
                require(len(files) <= 10000 and sum(f.file_size for f in files) <= 100*1024*1024, 'La planilla descomprimida excede el límite.')
                require(not any('vbaProject' in f.filename for f in files), 'No se admiten macros.')
                names = {f.filename for f in files}
                if suffix == '.xlsx':
                    require('xl/workbook.xml' in names, 'Estructura XLSX inválida.')
                    return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 1
                require('content.xml' in names and archive.read('mimetype') == b'application/vnd.oasis.opendocument.spreadsheet', 'Estructura ODS inválida.')
                return 'application/vnd.oasis.opendocument.spreadsheet', 1
        if suffix == '.txt':
            content.decode('utf-8')
            return 'text/plain', 1
        Image.MAX_IMAGE_PIXELS = 20000000
        with Image.open(BytesIO(content)) as image:
            require(image.format in ('PNG', 'JPEG', 'WEBP') and image.width*image.height <= 20000000, 'Imagen inválida o demasiado grande.')
            mime = Image.MIME[image.format]
            require(suffix in ('.jpg','.jpeg','.png','.webp'), 'Extensión de imagen inválida.')
            image.verify()
            return mime, 1
    except DomainError:
        raise
    except Exception:
        raise DomainError('No pudimos abrir el archivo. Verificá su formato antes de subirlo.') from None


def store_document(work, content, filename, payload):
    roles(*EDITORS, 'inspector', 'empresa', 'administrativo')
    mime, pages = inspect_file(content, filename)
    classification = payload.get('classification', 'interno')
    require(classification in ('publico','interno','reservado','confidencial'), 'Clasificación inválida.')
    if g.user.role == 'empresa':
        classification = 'reservado'
    if classification=='confidencial':
        roles('super_admin','admin','direccion_general')
    if classification=='publico':
        roles('super_admin','admin','direccion_general','director_obra')
    company_id = g.user.company_id if g.user.role == 'empresa' else work.company_id if classification == 'reservado' else None
    previous = None
    if payload.get('previous_id'):
        previous = document_for(int(payload['previous_id']))
        require(previous.work_id == work.id and previous.status not in ('eliminado','sustituido'), 'Versión anterior no disponible.', 409)
    record_id = payload.get('record_id')
    if record_id:
        require(Record.query.filter_by(id=int(record_id), work_id=work.id).first(), 'Registro asociado no encontrado.')
    key, digest = get_document_storage().put(content)
    document = Document(work_id=work.id, name=filename[:250], kind=payload.get('kind','documento')[:60], stage=work.stage, classification=classification, company_id=company_id, author_id=g.user.id, record_id=int(record_id) if record_id else None, storage_key=key, sha256=digest, mime=mime, size=len(content), pages=pages)
    if previous:
        document.group_id, document.version = previous.group_id, previous.version+1
        previous.status = 'sustituido'
        Chunk.query.filter_by(document_id=previous.id).delete()
    db.session.add(document)
    db.session.flush()
    history(work.id, 'documento', document.id, 'cargar_version', details={'version':document.version,'sha256':digest})
    if document.kind == 'portada':
        require(mime.startswith('image/'), 'La portada debe ser una imagen.')
        work.cover_id = document.id
    return document


def delete_document(document):
    roles(*EDITORS, 'empresa')
    from ..models.domain import PaymentAttempt, Procedure
    require(not PaymentAttempt.query.filter_by(receipt_id=document.id).first(), 'El comprobante de transferencia debe conservarse.', 409)
    for procedure in Procedure.query.filter_by(work_id=document.work_id):
        require(document.id not in procedure.data.get('document_ids', []), 'La evidencia de un trámite debe conservarse.', 409)
    approved = Certificate.query.filter_by(work_id=document.work_id, status='aprobado').filter(db.or_(Certificate.invoice_id == document.id, Certificate.certificate_document_id == document.id, Certificate.payment_document_id == document.id)).first()
    require(not approved, 'Un documento de certificado aprobado debe conservarse.', 409)
    from ..models.domain import Rectification
    for correction in Rectification.query.join(Certificate,Rectification.certificate_id==Certificate.id).filter(Certificate.work_id==document.work_id,Rectification.status=='aprobada'):
        require(correction.snapshot.get('document_id')!=document.id,'El anexo de rectificación aprobado debe conservarse.',409)
    for record in Record.query.filter_by(work_id=document.work_id, kind='recepcion'):
        require(document.id not in record.data.get('document_ids', []), 'Un acta de recepción debe conservarse.', 409)
    if g.user.role == 'empresa':
        require(document.author_id == g.user.id, 'Sólo podés retirar tus documentos.', 403)
    document.status = 'eliminado'
    document.ingestion = 'eliminado'
    Chunk.query.filter_by(document_id=document.id).delete()
    history(document.work_id, 'documento', document.id, 'eliminacion_logica')
