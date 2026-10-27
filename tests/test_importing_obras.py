from io import BytesIO
import openpyxl
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table,TableRow,TableCell
from odf.text import P
from app.services.importing import preview

def xlsx(rows):
    book=openpyxl.Workbook();sheet=book.active
    for row in rows:sheet.append(row)
    output=BytesIO();book.save(output);return output.getvalue()

def test_valid_preview_and_duplicate_error():
    headers=['codigo','descripcion','unidad','cantidad','precio_unitario','leyes_sociales','avance']
    rows=[headers,['1','Implantación','m2',10,200,.121,25]]
    p=preview(xlsx(rows),'r.xlsx','rubrado')
    assert p['rows'][0]['quantity']=='10' and not p['errors'] and p['requires_confirmation']
    assert preview(xlsx([*rows,rows[1]]),'r.xlsx','rubrado')['errors']

def test_missing_external_invalid_formula_and_range():
    rows=[['codigo','descripcion','unidad','cantidad','precio_unitario','avance'],['A','Prueba','m2',10,"='[1]Ausente'!A1",101],['B','Otro','m2',10,'=1/0',20]]
    p=preview(xlsx(rows),'f.xlsx','avance')
    assert any('externa' in e for e in p['errors']) and any('cero' in e for e in p['errors'])

def test_group_subtotal_not_double_counted():
    book=openpyxl.Workbook();sheet=book.active;sheet.title='Rubrado ARAUCA'
    sheet.append(['','1','Ítem','m2',2,100,'=E1*F1'])
    sheet.append(['','2','Ítem dos','m2',1,50,'=E2*F2'])
    sheet.append(['','G','Grupo','global',1,'=SUM(G1:G2)','=E3*F3'])
    out=BytesIO();book.save(out)
    p=preview(out.getvalue(),'g.xlsx','rubrado')
    assert len(p['rows'])==2 and sum(float(r['quantity'])*float(r['unit_price']) for r in p['rows'])==250
    assert any('subtotal' in w for w in p['warnings'])

def test_ods_private_professionals():
    book=OpenDocumentSpreadsheet();table=Table(name='Registro')
    for values in [['NOMBRE','DIRECCIÓN','F.NAC','C.I','TELÉFONO','CELULAR','CORREO ELECTRÓNICO','LOCALIDAD'],['Profesional sintético','Demo','','DEMO-ID','','','demo@demo.invalid','Minas']]:
        row=TableRow()
        for value in values:
            cell=TableCell(valuetype='string');cell.addElement(P(text=value));row.addElement(cell)
        table.addElement(row)
    book.spreadsheet.addElement(table);out=BytesIO();book.write(out)
    p=preview(out.getvalue(),'registro.ods','profesionales')
    assert p['rows'][0]['registration']=='DEMO-ID' and len(p['rows'])==1
