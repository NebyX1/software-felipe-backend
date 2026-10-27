from flask import request,g
from ..extensions import db
from ..models.domain import ImportBatch, Professional
from ..services.access import authenticated,work_for,roles,EDITORS,history
from ..services.documents import store_document
from ..services.importing import preview
from ..services.works import save_contract
from ..services.errors import require
from .interventions import body
from . import api_bp


@api_bp.post('/works/<int:work_id>/imports/preview')
@authenticated
def import_preview(work_id):
    work=work_for(work_id,True)
    kind=request.form.get('kind','rubrado')
    roles('super_admin','admin') if kind=='profesionales' else roles(*EDITORS,'empresa')
    file=request.files.get('file')
    require(file and file.filename.lower().endswith(('.xlsx','.ods')),'Adjuntá XLSX u ODS.')
    content=file.read(20*1024*1024+1)
    doc=store_document(work,content,file.filename,{'kind':'importacion','classification':'confidencial' if kind=='profesionales' else 'reservado'})
    result=preview(content,file.filename,kind,request.form.get('sheet'),request.form.get('advance_column'))
    batch=ImportBatch(work_id=work_id,user_id=g.user.id,document_id=doc.id,kind=kind,preview=result,sha256=doc.sha256)
    db.session.add(batch)
    db.session.commit()
    return {'import':batch.to_dict()},201


@api_bp.post('/imports/<int:batch_id>/confirm')
@authenticated
def confirm_import(batch_id):
    batch=ImportBatch.query.filter_by(id=batch_id,user_id=g.user.id).with_for_update().first()
    require(batch,'Importación no encontrada.',404)
    work=work_for(batch.work_id,True)
    data=body()
    require(data.get('confirm') is True and data.get('sha256')==batch.sha256,'Confirmá la previsualización del original vigente.')
    require(batch.status=='previsualizacion','Importación ya procesada.',409)
    require(not batch.preview['errors'],'La planilla contiene errores; corregí el original y volvé a previsualizar.',409)
    rows=batch.preview['rows']
    require(rows,'No hay filas para importar.')
    if batch.kind=='rubrado':
        roles(*EDITORS)
        contract=save_contract(work,{**data.get('contract',{}),'lines':rows})
        result={'contract_id':contract.id}
    elif batch.kind=='profesionales':
        roles('super_admin','admin')
        require(all(r['registration'] for r in rows),'El registro tiene identificaciones faltantes.')
        for row in rows:
            professional=Professional.query.filter_by(registration=row['registration']).first() or Professional(registration=row['registration'])
            professional.name,professional.contact,professional.source=row['name'],row['contact'],'Importación privada documento '+str(batch.document_id)
            db.session.add(professional)
        result={'professionals':len(rows)}
    else:
        # Confirmation produces structured inputs; saving a certificate still follows its circuit.
        result={'advances':{row['code']:row['advance'] for row in rows},'mode':batch.preview['mode_hint']}
    batch.status='confirmado'
    history(work.id,'importacion',batch.id,'confirmar',details={'kind':batch.kind,'sha256':batch.sha256})
    db.session.commit()
    return {'result':result,'import':batch.to_dict()}
