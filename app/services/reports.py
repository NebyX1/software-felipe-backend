"""Reports come from immutable certificate snapshots and authorized queries."""
from io import BytesIO
import csv
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from ..extensions import db
from ..models.domain import Document
from ..infrastructure.storage import get_document_storage
from flask import g


def pdf_report(title, paragraphs, headers=None, rows=None):
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles['BodyText'].fontSize = 9
    styles['BodyText'].leading = 13
    story = [Paragraph(escape(title), styles['Title']), Paragraph('Lavalleja · Gestión y seguimiento de obras · DEMOSTRACIÓN', styles['BodyText']), Spacer(1, 14)]
    story.extend(Paragraph(escape(str(p)), styles['BodyText']) for p in paragraphs)
    story.append(Spacer(1, 12))
    if headers:
        data = [[Paragraph(escape(str(v)), styles['BodyText']) for v in headers]]
        data.extend([Paragraph(escape(str(v)), styles['BodyText']) for v in row] for row in rows or [])
        width = A4[0]-72
        widths = [width/len(headers)]*len(headers)
        if len(headers) == 6:
            widths = [45, 195, 42, 55, 55, width-392]
        table = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e2ecf4')), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('GRID',(0,0),(-1,-1),.3,colors.HexColor('#ccd5dd')), ('LEFTPADDING',(0,0),(-1,-1),5), ('RIGHTPADDING',(0,0),(-1,-1),5)]))
        story.append(table)
    def footer(canvas, document):
        canvas.setFont('Helvetica', 8)
        canvas.drawString(36, 24, 'Documento de demostración. No constituye firma, expediente oficial ni pago real.')
        canvas.drawRightString(A4[0]-36, 24, str(document.page))
    SimpleDocTemplate(output, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=48).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def certificate_pdfs(cert, work, *, commit=True):
    snapshot = cert.approved_snapshot
    calc = snapshot['calculation']
    common = [f"Obra: {snapshot.get('work',{}).get('name',work.name)} · {work.code}", f"Período: {snapshot['period']} · {snapshot['dates'][0]} a {snapshot['dates'][1]}", f"Contrato: {snapshot['contract']['number']} · versión {snapshot['contract']['version']}", f"Factura: {snapshot['invoice_number']} · documento {snapshot['invoice']['name']} · hash {snapshot['invoice']['sha256']}", *[f"{a['role']}: {a['name']} (usuario {a['actor_id']})" for a in snapshot['approvals']], f"Subtotal $ {calc['base']} · IVA $ {calc['iva']} · LLSS $ {calc['social']} ({calc['social_payment']})", f"ICC inicial {calc['icc_initial']} · período {calc['icc_current']} · base elegible $ {calc['icc_base']}", f"Ajuste $ {calc['adjustment']} · IVA ajuste $ {calc['adjustment_iva']} · Total a pagar $ {calc['payable']}"]
    rows = [[r['code'], r['description'], r['unit'], str(round(float(r['period'])*100, 4))+'%', str(round(float(r['accumulated'])*100, 4))+'%', r['amount']] for r in calc['lines']]
    content = pdf_report('Certificación mensual de obra', common, ['Código','Descripción','Unidad','Período','Acum.','Importe $'], rows)
    note = pdf_report('Solicitud de pago · Expediente DEMO', [*common, 'Se solicita tramitar el pago ficticio de la factura referenciada por el circuito Hacienda, Secretaría General, resolución y Contaduría/Tesorería.'])
    storage = get_document_storage()
    for field, kind, name, binary in [('certificate_document_id','certificado',f'certificado-{cert.id}.pdf',content), ('payment_document_id','nota_pago',f'nota-pago-{cert.id}.pdf',note)]:
        if getattr(cert, field):
            continue
        key, digest = storage.put(binary)
        document = Document(work_id=work.id, name=name, kind=kind, stage=work.stage, classification='reservado', company_id=work.company_id, author_id=g.user.id, storage_key=key, sha256=digest, mime='application/pdf', size=len(binary), status='validado')
        db.session.add(document)
        db.session.flush()
        setattr(cert, field, document.id)
    if commit:
        db.session.commit()


def csv_report(headers, rows):
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([("'"+str(v)) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in row])
    return output.getvalue().encode('utf-8-sig')
