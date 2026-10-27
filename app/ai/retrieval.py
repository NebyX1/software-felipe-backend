from collections import Counter
from io import BytesIO
import math
import re
import unicodedata
from pypdf import PdfReader
from flask import g
from ..extensions import db
from ..models.domain import Document,Chunk
from ..services.access import documents_query,history
from ..services.errors import require,DomainError
from ..infrastructure.storage import get_document_storage


def terms(text):
    normalized=''.join(c for c in unicodedata.normalize('NFD',text.lower()) if not unicodedata.combining(c))
    return re.findall(r'[a-z0-9]{3,}',normalized)


def ingest(document):
    document.ingestion='procesando'
    db.session.commit()
    try:
        content=get_document_storage().read(document.storage_key)
        if document.mime=='application/pdf':
            pages=[p.extract_text() or '' for p in PdfReader(BytesIO(content)).pages]
        elif document.mime=='text/plain':
            pages=[content.decode('utf-8')]
        elif 'spreadsheet' in document.mime:
            from ..services.importing import read_workbook
            tables,_,errors=read_workbook(content,document.name)
            require(not errors,'La planilla tiene errores y no se indexa como información válida.')
            pages=['Hoja '+s['sheet']+'\n'+'\n'.join(' | '.join(str(v or '') for v in row) for row in s['rows']) for s in tables]
        else:
            raise DomainError('Esta imagen requiere transcripción revisada; no se simuló lectura visual.')
        require(any(p.strip() for p in pages),'El PDF no contiene texto digital; adjuntá una transcripción revisada.')
        require(sum(len(p) for p in pages)<=2000000,'Documento demasiado extenso para indexación.')
        Chunk.query.filter_by(document_id=document.id).delete()
        position=0
        for page_number,text in enumerate(pages,1):
            for start in range(0,len(text),1000):
                fragment=text[start:start+1200].strip()
                if fragment:
                    db.session.add(Chunk(document_id=document.id,page=page_number,position=position,text=fragment))
                    position+=1
        document.ingestion,document.ingestion_error='listo',None
        history(document.work_id,'documento',document.id,'indexar',details={'version':document.version,'chunks':position})
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        document=db.session.get(Document,document.id)
        document.ingestion='fallido'
        document.ingestion_error=error.message if isinstance(error,DomainError) else 'No se pudo procesar el documento. Podés reintentar.'
        db.session.commit()
    return document


def retrieve(work_id,query,include_history=False):
    # SQL permission filter is applied BEFORE any candidate text is loaded/scored.
    allowed=documents_query(work_id).filter(Document.ingestion=='listo')
    if not include_history:
        allowed=allowed.filter(Document.status.notin_(('sustituido','archivado')))
    document_ids=allowed.with_entities(Document.id).statement
    rows=Chunk.query.join(Document,Chunk.document_id==Document.id).filter(Chunk.document_id.in_(document_ids)).all()
    search=Counter(terms(query))
    doc_frequency=Counter()
    counts=[]
    for chunk in rows:
        count=Counter(terms(chunk.text))
        counts.append(count)
        doc_frequency.update(count.keys())
    scored=[]
    for chunk,count in zip(rows,counts):
        score=sum(search[t]*math.log(1+len(rows)/(1+doc_frequency[t]))*count[t]/(count[t]+1) for t in search if count[t])
        if score:
            scored.append((score,chunk))
    sources=[]
    for _,chunk in sorted(scored,key=lambda item:(-item[0],item[1].id))[:8]:
        document=db.session.get(Document,chunk.document_id)
        sources.append({'id':chunk.id,'document_id':document.id,'name':document.name,'version':document.version,'page':chunk.page,'sha256':document.sha256,'text':chunk.text,'url':f'/api/documents/{document.id}/download'})
    return sources
