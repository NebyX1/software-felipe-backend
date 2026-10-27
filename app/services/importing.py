"""Read-only, bounded workbook parsing. Formulas are interpreted, never executed."""
import ast
from io import BytesIO
import re
import zipfile
from decimal import Decimal
import unicodedata
import openpyxl
from openpyxl.utils.cell import range_boundaries, get_column_letter
from odf.opendocument import load
from odf.table import Table, TableRow, TableCell
from odf import teletype
from .economics import decimal, money
from .errors import require, DomainError


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').lower().strip()) if not unicodedata.combining(c))


class FormulaReader:
    def __init__(self, workbook):
        self.book, self.cache, self.visiting = workbook, {}, set()

    def value(self, sheet, cell):
        key = (sheet, cell.replace('$',''))
        if key in self.cache:
            return self.cache[key]
        require(key not in self.visiting, f'Referencia circular: {sheet}!{cell}.')
        value = self.book[sheet][key[1]].value
        if value is None:
            return Decimal(0)
        if not isinstance(value, str) or not value.startswith('='):
            require(not str(value).startswith(('#REF!', '#DIV/0!', '#VALUE!', '#NAME?', '#N/A')), f'Error de celda {sheet}!{cell}: {value}')
            return value
        require('[' not in value and '#REF!' not in value, f'Referencia externa ausente o rota: {sheet}!{cell}: {value}')
        self.visiting.add(key)
        try:
            expression = value[1:].lstrip('+')
            references = []
            def capture(match):
                references.append((match.group(1) or sheet, match.group(2)))
                return f'R{len(references)-1}'
            expression = re.sub(r"(?:'([^']+)'!)?(\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?)", capture, expression)
            tree = ast.parse(expression, mode='eval')
            def evaluate(node):
                if isinstance(node, ast.Constant) and isinstance(node.value,(int,float)):
                    return Decimal(str(node.value))
                if isinstance(node, ast.Name) and re.fullmatch(r'R\d+',node.id):
                    name, location = references[int(node.id[1:])]
                    if ':' in location:
                        a,b,c,d = range_boundaries(location.replace('$',''))
                        require((c-a+1)*(d-b+1) <= 10000, 'Rango de fórmula demasiado grande.')
                        return [self.value(name, f'{get_column_letter(col)}{row}') for row in range(b,d+1) for col in range(a,c+1)]
                    return self.value(name,location)
                if isinstance(node, ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
                    result = decimal(evaluate(node.operand))
                    return -result if isinstance(node.op,ast.USub) else result
                if isinstance(node,ast.BinOp):
                    left,right = decimal(evaluate(node.left)),decimal(evaluate(node.right))
                    if isinstance(node.op,ast.Add): return left+right
                    if isinstance(node.op,ast.Sub): return left-right
                    if isinstance(node.op,ast.Mult): return left*right
                    if isinstance(node.op,ast.Div):
                        require(right != 0, f'División por cero: {sheet}!{cell}.')
                        return left/right
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id.upper() == 'SUM':
                    values=[]
                    for arg in node.args:
                        part=evaluate(arg)
                        values.extend(part if isinstance(part,list) else [part])
                    return sum((decimal(v) for v in values if isinstance(v,(int,float,Decimal))),Decimal(0))
                raise DomainError(f'Fórmula no soportada: {sheet}!{cell}: {value}')
            result = evaluate(tree.body)
            self.cache[key] = result
            return result
        except (SyntaxError,KeyError,TypeError):
            raise DomainError(f'Fórmula inválida: {sheet}!{cell}: {value}') from None
        finally:
            self.visiting.remove(key)


def read_workbook(content, filename):
    warnings, errors, tables = [], [], []
    if filename.lower().endswith('.ods'):
        document = load(BytesIO(content))
        for sheet in document.spreadsheet.getElementsByType(Table):
            grid=[]
            for row in sheet.getElementsByType(TableRow):
                values=[]
                for cell in row.getElementsByType(TableCell):
                    repeat = int(cell.getAttribute('numbercolumnsrepeated') or 1)
                    value = cell.getAttribute('value') or teletype.extractText(cell)
                    if cell.getAttribute('formula'):
                        errors.append(f"{sheet.getAttribute('name')}: fórmula ODS requiere valores originales verificables; no se usa caché.")
                    if repeat <= 100:
                        values.extend([value]*repeat)
                if any(values):
                    grid.extend([values]*min(100,int(row.getAttribute('numberrowsrepeated') or 1)))
                require(len(grid) <= 10000, 'Demasiadas filas ODS.')
            tables.append({'sheet':sheet.getAttribute('name'),'rows':grid})
    else:
        workbook = openpyxl.load_workbook(BytesIO(content),data_only=False,keep_links=True)
        cached = openpyxl.load_workbook(BytesIO(content),data_only=True)
        reader=FormulaReader(workbook)
        with zipfile.ZipFile(BytesIO(content)) as archive:
            for name in archive.namelist():
                if name.startswith('xl/externalLinks/') and name.endswith('.rels'):
                    from urllib.parse import unquote
                    source=unquote(archive.read(name).decode('utf-8'))
                    errors.append('Fuente externa ausente: '+source)
        for name, definition in workbook.defined_names.items():
            if '#REF!' in definition.attr_text:
                warnings.append(f'Nombre definido roto: {name} = {definition.attr_text}.')
        for sheet in workbook:
            require(sheet.max_row <= 10000 and sheet.max_column <= 500, 'La planilla supera los límites de análisis.')
            grid=[]
            for row in sheet:
                values=[]
                for cell in row:
                    try:
                        value=reader.value(sheet.title,cell.coordinate)
                        if isinstance(value,Decimal):
                            stored=cached[sheet.title][cell.coordinate].value
                            if isinstance(stored,(int,float)) and abs(value-Decimal(str(stored))) > Decimal('.01'):
                                warnings.append(f'Caché difiere del cálculo: {sheet.title}!{cell.coordinate}.')
                            value=str(value)
                    except DomainError as error:
                        errors.append(error.message)
                        value=None
                    values.append(value)
                grid.append(values)
            aggregates = [row for row in range(1,sheet.max_row+1) if any(isinstance(sheet.cell(row,col).value,str) and re.search(r'SUM\(.*\d+:.*\d+',sheet.cell(row,col).value,re.I) for col in (6,7))]
            tables.append({'sheet':sheet.title,'rows':grid,'aggregate_rows':aggregates,'merged':[str(m) for m in sheet.merged_cells],'grouped_rows':[r for r,d in sheet.row_dimensions.items() if d.outlineLevel or d.hidden]})
    return tables,warnings,errors


def preview(content, filename, kind, sheet_name=None, advance_column=None):
    tables,warnings,errors = read_workbook(content,filename)
    require(kind in ('rubrado','avance','profesionales'), 'Tipo de importación inválido.')
    selected = next((s for s in tables if s['sheet'] == sheet_name),tables[0] if tables else None)
    require(selected, 'La planilla no contiene hojas.')
    rows=[]
    if kind == 'profesionales':
        headers=next((r for r in selected['rows'] if normalize(r[0] if r else '') == 'nombre'),None)
        require(headers, 'Falta encabezado NOMBRE del registro.')
        for index,data in enumerate(selected['rows']):
            if data == headers or not data or not data[0]:
                continue
            padded=[*data,*['']*8]
            registration=str(padded[3] or '').strip()
            if not registration:
                import hashlib
                registration='SIN-CI-'+hashlib.sha256(content).hexdigest()[:16]+'-'+str(index+1)
                warnings.append(f'Fila {index+1}: CI ausente; se conserva vacía y se asigna identificador interno {registration}, sujeto a confirmación. No es identidad institucional.')
            rows.append({'name':str(padded[0]),'registration':registration,'contact':{'ci':str(padded[3] or ''),'address':str(padded[1]),'birth_date':str(padded[2]),'phone':str(padded[4]),'mobile':str(padded[5]),'email':str(padded[6]),'locality':str(padded[7])},'source_row':index+1})
    else:
        molino = any(normalize(v) == 'rubrado arauca' for v in [selected['sheet']])
        generic_header=None
        for data in selected['rows']:
            normalized=[normalize(v) for v in data]
            if 'code' in normalized or 'codigo' in normalized:
                generic_header=normalized
                break
        seen=set()
        chapter='General'
        for index,data in enumerate(selected['rows']):
            values=[*data,*[None]*32]
            if index+1 in selected.get('aggregate_rows',[]):
                warnings.append(f'Fila {index+1}: subtotal/grupo conservado como referencia, no sumado como ítem.')
                continue
            if generic_header:
                if [normalize(v) for v in data] == generic_header:
                    continue
                mapping=dict(zip(generic_header,values))
                code=mapping.get('code',mapping.get('codigo'))
                description=mapping.get('description',mapping.get('descripcion'))
                unit=mapping.get('unit',mapping.get('unidad'))
                quantity=mapping.get('quantity',mapping.get('cantidad'))
                price=mapping.get('unit_price',mapping.get('precio_unitario'))
                social=mapping.get('social_rate',mapping.get('leyes_sociales','0'))
                advance=mapping.get('advance',mapping.get('avance'))
            else:
                offset=1 if molino else 0
                code,description,unit,quantity,price=values[offset:offset+5]
                if not unit or normalize(unit) not in ('m2','m3','ml','ml.','un','un.','global','gl','kg','h','l','t'):
                    if description and not quantity:
                        chapter=str(description)
                    continue
                social='0'
                col = advance_column or ('AX' if molino else 'P' if 'mayo' in normalize(selected['sheet']) else 'J')
                from openpyxl.utils.cell import column_index_from_string
                position=column_index_from_string(col)-1
                advance=values[position] if position<len(values) else None
            if not description or not unit or quantity is None or price is None:
                continue
            if normalize(quantity) in ('cantidad','cant.') or normalize(price) in ('precio','precio unitario','p. unitario'):
                continue
            code=str(code or f'EXTRA-{index+1}')
            if code in seen:
                errors.append(f'Código duplicado {code}, fila {index+1}; separar capítulos antes de confirmar.')
            seen.add(code)
            try:
                qty,p=decimal(quantity),decimal(price)
                if not generic_header and not molino:
                    social=str(decimal(values[5])/p) if p else '0'
                require(qty>0 and p>=0,'Cantidad/precio inválidos.')
                if not generic_header:
                    total=values[6]
                    if total and abs(decimal(total)-qty*p)>Decimal('.01'):
                        errors.append(f'Importe incoherente: fila {index+1}, cantidad × precio no coincide.')
                unit=normalize(unit).removesuffix('.')
                unit='global' if unit=='gl' else unit
                require(unit in ('m2','m3','ml','un','global','kg','h','l','t'),'Unidad desconocida; definí equivalencia antes de importar.')
                if kind=='avance':
                    a=decimal(advance)
                    require(0<=a<=1 if not generic_header else 0<=a<=100,'Avance fuera de rango.')
                    rows.append({'code':code,'advance':str(a if generic_header else a*100),'source_row':index+1})
                else:
                    rows.append({'code':code,'description':str(description),'unit':unit,'quantity':str(qty),'unit_price':str(p),'social_rate':str(social),'chapter':chapter,'kind':'imprevisto' if index>=177 and molino or index>=92 and not molino else 'basico','source_row':index+1})
            except DomainError as error:
                errors.append(f'Fila {index+1}: {error.message}')
    return {'kind':kind,'sheet':selected['sheet'],'sheets':[{'name':s['sheet'],'rows':len(s['rows'])} for s in tables],'rows':rows,'warnings':list(dict.fromkeys(warnings))[:200],'errors':list(dict.fromkeys(errors))[:200],'requires_confirmation':True,'mode_hint':'periodo' if normalize(selected['sheet'])=='rubrado arauca' else 'acumulado' if 'mayo' in normalize(selected['sheet']) else 'periodo','notice':'El original se conserva. Las fórmulas no se ejecutan; cálculos interpretados sin usar cachés como autoridad.'}
