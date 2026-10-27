import json
from flask import request,g,Response,stream_with_context
from ..extensions import db,limiter
from ..models.domain import ChatTurn,Chunk,Document,Company,AuthSession
from flask_jwt_extended import get_jwt
from ..models import User
from ..services.errors import DomainError
from ..services.access import authenticated,work_for,document_for,roles,EDITORS,history
from ..services.errors import require
from ..ai.retrieval import ingest,retrieve
from ..ai import provider
from .interventions import body
from . import api_bp


@api_bp.post('/documents/<int:document_id>/ingest')
@authenticated
def index(document_id):
    document=document_for(document_id)
    roles(*EDITORS,'empresa','inspector','administrativo')
    require(document.status not in ('eliminado','sustituido'),'Esta versión no es vigente.',409)
    return {'document':ingest(document).to_dict()}


@api_bp.delete('/documents/<int:document_id>/index')
@authenticated
def remove_index(document_id):
    document=document_for(document_id)
    roles(*EDITORS,'empresa')
    Chunk.query.filter_by(document_id=document_id).delete()
    document.ingestion='pendiente'
    history(document.work_id,'documento',document.id,'eliminar_indice')
    db.session.commit()
    return {'document':document.to_dict()}


@api_bp.get('/works/<int:work_id>/search')
@authenticated
def search(work_id):
    work_for(work_id)
    query=request.args.get('q','').strip()
    require(0<len(query)<=3000,'Ingresá una consulta de hasta 3000 caracteres.')
    return {'sources':retrieve(work_id,query),'retrieval':'textual autorizado por obra, empresa, clasificación y versión; sin embeddings'}


@api_bp.get('/works/<int:work_id>/chat')
@authenticated
def chat_history(work_id):
    work_for(work_id)
    turns=[]
    for turn in ChatTurn.query.filter_by(work_id=work_id,user_id=g.user.id).order_by(ChatTurn.id.desc()).limit(50):
        sources=turn.sources or []
        try:
            if all(document_for(s['document_id']) for s in sources):turns.append(turn.to_dict())
        except DomainError:
            continue
    return {'turns':turns}


@api_bp.post('/works/<int:work_id>/chat')
@authenticated
@limiter.limit('10/minute')
def chat(work_id):
    work_for(work_id)
    data=body()
    query=data.get('query','').strip()
    require(0<len(query)<=3000,'Ingresá una consulta de hasta 3000 caracteres.')
    sources=retrieve(work_id,query)
    require(sources,'No hay fragmentos autorizados que respondan a esta consulta. Indexá documentación o ajustá la búsqueda.',409,'no_sources')
    turn=ChatTurn(work_id=work_id,user_id=g.user.id,question=query,sources=sources)
    db.session.add(turn)
    db.session.commit()  # No DB transaction remains open while waiting for the model.
    turn_id,user_id=turn.id,g.user.id
    session_jti=get_jwt()['jti']
    def events():
        g.user=db.session.get(User,user_id)
        turn=db.session.get(ChatTurn,turn_id)
        work_for(work_id)
        yield 'event: context\ndata: '+json.dumps({'turn_id':turn.id,'sources':[{k:v for k,v in s.items() if k!='text'} for s in sources]},ensure_ascii=False)+'\n\n'
        try:
            answer=None
            for event,payload in provider.answer_stream(query,sources):
                if event=='done':answer=payload
                elif event=='heartbeat':yield ': keepalive\n\n'
                elif event=='token':
                    db.session.rollback()
                    g.user=db.session.get(User,user_id)
                    require(g.user and g.user.is_active,'La sesión dejó de estar habilitada.',403)
                    require(AuthSession.query.filter_by(jti=session_jti,revoked=False).first(),'La sesión se cerró.',403)
                    if g.user.company_id:
                        require(db.session.get(Company,g.user.company_id).status=='activa','Empresa suspendida.',403)
                    work_for(work_id)
                    require(all(document_for(s['document_id']).status not in ('eliminado','sustituido') for s in sources),'El contexto cambió durante la consulta.',409)
                    yield 'event: token\ndata: '+json.dumps(payload,ensure_ascii=False)+'\n\n'
            require(answer,'No llegó una respuesta completa.',503)
            # Re-check before sending a completed answer if access/version changed meanwhile.
            work_for(work_id)
            require(all(document_for(s['document_id']).status not in ('eliminado','sustituido') for s in sources),'La documentación cambió durante la consulta.',409)
            turn.status,turn.answer='completo',answer['message']
            turn.sources=[s for s in sources if s['id'] in answer['citations']]
            history(work_id,'ia',turn.id,'consulta_documental',details={'source_ids':answer['citations']})
            db.session.commit()
            yield 'event: done\ndata: '+json.dumps({'turn':turn.to_dict()},ensure_ascii=False)+'\n\n'
        except Exception as error:
            db.session.rollback()
            turn.status='fallido'
            turn.error_code=error.code if isinstance(error,provider.ProviderUnavailable) else 'context_changed'
            db.session.commit()
            yield 'event: error\ndata: '+json.dumps({'code':turn.error_code,'message':str(error) if isinstance(error,provider.ProviderUnavailable) else 'El contexto no está disponible. Probá nuevamente.'},ensure_ascii=False)+'\n\n'
    response=Response(stream_with_context(events()),mimetype='text/event-stream')
    response.headers['X-Accel-Buffering']='no'
    return response


@api_bp.post('/ai/import-mapping')
@authenticated
def mapping():
    roles(*EDITORS)
    headers=body().get('headers')
    require(isinstance(headers,list) and 0<len(headers)<=30 and all(isinstance(h,str) and len(h)<=100 for h in headers),'Encabezados inválidos.')
    try:
        return {'proposal':provider.propose_mapping(headers),'requires_confirmation':True}
    except provider.ProviderUnavailable as error:
        return {'code':error.code,'message':str(error)},503
