from io import BytesIO
import hashlib
from flask import request, g, current_app, send_file
from flask_jwt_extended import get_jwt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from ..extensions import db
from ..models import User
from ..models.domain import Document, Annotation, AuthSession,Company
from ..services.access import authenticated, work_for, document_for, documents_query, history, roles, EDITORS
from ..services.documents import store_document, delete_document
from ..services.errors import require, DomainError
from ..services.economics import decimal
from ..services.works import text
from ..infrastructure.storage import get_document_storage
from .interventions import body
from . import api_bp


@api_bp.route('/works/<int:work_id>/documents', methods=['GET','POST'])
@authenticated
def documents(work_id):
    work = work_for(work_id, request.method == 'POST')
    if request.method == 'GET':
        return {'documents': [d.to_dict() for d in documents_query(work_id).order_by(Document.created_at.desc())]}
    file = request.files.get('file')
    require(file and file.filename, 'Adjuntá un archivo.')
    document = store_document(work, file.read(20*1024*1024+1), file.filename, request.form)
    db.session.commit()
    return {'document': document.to_dict()}, 201


def download(document):
    content = get_document_storage().read(document.storage_key)
    require(hashlib.sha256(content).hexdigest() == document.sha256, 'El archivo no coincide con su hash de integridad.', 409)
    history(document.work_id, 'documento', document.id, 'descargar')
    db.session.commit()
    response = send_file(BytesIO(content), mimetype=document.mime, as_attachment=request.args.get('inline') != '1', download_name=document.name)
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


@api_bp.get('/documents/<int:document_id>/download')
@authenticated
def document_download(document_id):
    return download(document_for(document_id))


@api_bp.post('/documents/<int:document_id>/link')
@authenticated
def temporary_link(document_id):
    document = document_for(document_id)
    token = URLSafeTimedSerializer(current_app.secret_key, salt='document-download').dumps({'document_id':document_id,'user_id':g.user.id,'jti':get_jwt()['jti']})
    history(document.work_id,'documento',document.id,'enlace_temporal')
    db.session.commit()
    return {'url': '/api/document-link/'+token, 'expires_in': 60}


@api_bp.get('/document-link/<token>')
def signed_download(token):
    try:
        payload = URLSafeTimedSerializer(current_app.secret_key, salt='document-download').loads(token,max_age=60)
    except (BadSignature,SignatureExpired):
        raise DomainError('El enlace expiró o no es válido.',403) from None
    session = AuthSession.query.filter_by(jti=payload['jti'],user_id=payload['user_id'],revoked=False).first()
    g.user = db.session.get(User,payload['user_id'])
    require(session and g.user and g.user.is_active and (not g.user.demo or current_app.config['DEMO_AUTH_ENABLED']), 'El acceso fue revocado.',403)
    if g.user.company_id:
        company=db.session.get(Company,g.user.company_id)
        require(company and company.status=='activa','Empresa suspendida.',403)
    return download(document_for(payload['document_id']))


@api_bp.delete('/documents/<int:document_id>')
@authenticated
def remove_document(document_id):
    document = document_for(document_id)
    work_for(document.work_id,True)
    delete_document(document)
    db.session.commit()
    return {'document':document.to_dict()}


@api_bp.post('/documents/<int:document_id>/transition')
@authenticated
def document_state(document_id):
    document=document_for(document_id);work_for(document.work_id,True)
    roles('super_admin','admin','direccion_general','director_obra','inspector')
    data=body();target=data.get('status');previous=document.status
    allowed={'cargado':{'validado','observado'},'observado':{'validado'},'validado':{'archivado'}}
    require(target in allowed.get(previous,set()),'Estado documental inválido.',409)
    from ..models.domain import Certificate
    require(not Certificate.query.filter_by(status='aprobado').filter(db.or_(Certificate.invoice_id==document.id,Certificate.certificate_document_id==document.id,Certificate.payment_document_id==document.id)).first(),'Documento de aprobación definitivo: conservá su estado.',409)
    comment=text(data.get('comment',''),'Comentario de revisión')
    document.status=target;history(document.work_id,'documento',document.id,'revisar',previous,target,{'comment':comment})
    db.session.commit();return {'document':document.to_dict()}


@api_bp.route('/documents/<int:document_id>/annotations',methods=['GET','POST'])
@authenticated
def annotations(document_id):
    document = document_for(document_id)
    if request.method == 'GET':
        return {'annotations':[a.to_dict() for a in Annotation.query.filter_by(document_id=document_id).order_by(Annotation.id)]}
    roles(*EDITORS,'inspector')
    data = body()
    x,y = decimal(data.get('x')),decimal(data.get('y'))
    require(0 <= x <= 1 and 0 <= y <= 1 and isinstance(data.get('page'),int) and 1 <= data['page'] <= document.pages,'Página o posición inválida.')
    annotation = Annotation(document_id=document_id,page=data['page'],x=x,y=y,text=text(data.get('text',''),'Anotación'),author_id=g.user.id)
    db.session.add(annotation)
    db.session.flush()
    history(document.work_id,'anotacion',annotation.id,'crear',details={'document_version':document.version})
    db.session.commit()
    return {'annotation':annotation.to_dict()},201
