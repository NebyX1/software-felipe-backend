"""Deterministic certificate engine. Rates belong to contract versions, not AI."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from .errors import require, DomainError

CENT = Decimal('0.01')
PRECISION = Decimal('0.00000001')


def decimal(value, name='valor'):
    require(not isinstance(value, bool) and value is not None and value != '', f'Falta {name}.')
    try:
        result = Decimal(str(value))
        require(result.is_finite() and abs(result) < Decimal('1e16'), f'{name} fuera de rango.')
        return result
    except (InvalidOperation, ValueError):
        raise DomainError(f'{name} debe ser decimal.') from None


def money(value):
    return decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def rate(value, name):
    number = decimal(value, name)
    require(0 <= number <= 1, f'{name} debe ser una fracción entre 0 y 1.')
    return number


def line_values(line):
    return line.to_dict() if hasattr(line, 'to_dict') else dict(line)


def calculate(lines, inputs, previous, rules, mode, icc_current=None,previous_quantities=None):
    require(mode in ('periodo', 'acumulado', 'cantidad', 'importe'), 'Modalidad de avance inválida.')
    require(isinstance(inputs, dict), 'El avance debe indicar código y valor por rubro.')
    catalog = [line_values(line) for line in lines]
    codes = {l['code'] for l in catalog}
    require(len(codes) == len(catalog) and set(inputs) <= codes, 'Rubros duplicados o desconocidos.')
    iva = rate(rules.get('iva_rate'), 'IVA contractual')
    social_payment = rules.get('social_payment', 'separado')
    require(social_payment in ('incluido', 'separado'), 'Definir cómo se pagan las leyes sociales.')
    groups = {key: Decimal(0) for key in ('basico', 'imprevisto', 'ampliacion')}
    base = social = eligible = full = Decimal(0)
    rows = []
    with localcontext() as ctx:
        ctx.prec = 40
        for line in catalog:
            code = line['code']
            quantity, price = decimal(line['quantity']), decimal(line['unit_price'])
            require(quantity > 0 and price >= 0, f'Cantidad/precio inválidos en {code}.')
            total = money(quantity * price)
            before = rate(previous.get(code, '0'), f'Acumulado anterior {code}')
            prior_quantity=decimal((previous_quantities or {}).get(code,str(quantity*before)))
            value = decimal(inputs.get(code, str(before) if mode == 'acumulado' else '0'), code)
            require(value >= 0, f'Avance negativo en {code}.')
            if mode == 'acumulado':
                accumulated, period = value / 100, value / 100 - prior_quantity/quantity
                if code not in inputs or value/100==before:
                    accumulated, period = prior_quantity/quantity, Decimal(0)
            elif mode == 'periodo':
                period, accumulated = value / 100, prior_quantity/quantity + value / 100
            elif mode == 'cantidad':
                period, accumulated = value / quantity, (prior_quantity+value)/quantity
            else:
                require(total > 0 or value == 0, f'Importe sin base positiva en {code}.')
                period = value / total if total else Decimal(0)
                accumulated = prior_quantity/quantity + period
            require(0<=accumulated<=1 and period>=0,f'El rubro {code} retrocede o supera el 100%.')
            exact_accumulated=accumulated
            accumulated_quantity=prior_quantity+value if mode=='cantidad' else quantity*exact_accumulated
            accumulated=accumulated.quantize(PRECISION,rounding=ROUND_HALF_UP)
            period=accumulated-before
            require(0 <= period <= 1 and 0 <= accumulated <= 1, f'El rubro {code} retrocede o supera el 100%.')
            amount = money(total * exact_accumulated)-money(total * prior_quantity/quantity)
            social_rate=rate(line.get('social_rate', '0'), 'LLSS')
            llss = money(total * social_rate * exact_accumulated)-money(total * social_rate * prior_quantity/quantity)
            kind = line.get('kind', 'basico')
            require(kind in groups, f'Tipo de rubro inválido: {kind}.')
            groups[kind] += amount
            base += amount
            social += llss
            full += total
            if line.get('icc_eligible', True):
                eligible += amount
            rows.append({**line, 'accumulated_quantity':str(accumulated_quantity),'previous_quantity':str(prior_quantity),'contract_total': str(total), 'previous': str(before.quantize(PRECISION)), 'period': str(period.quantize(PRECISION)), 'accumulated': str(accumulated.quantize(PRECISION)), 'amount': str(amount), 'social': str(llss)})
        adjustment = Decimal(0)
        initial = rules.get('icc_initial')
        if initial is not None and initial != '':
            require(icc_current is not None, 'Falta el ICC del período.')
            index0, index = decimal(initial, 'ICC inicial'), decimal(icc_current, 'ICC período')
            require(index0 > 0 and index > 0, 'Los índices ICC deben ser positivos.')
            adjustment = money((index / index0 - 1) * eligible)
        vat, adjustment_vat = money(base * iva), money(adjustment * iva)
        payable = money(base + vat + adjustment + adjustment_vat + (social if social_payment == 'incluido' else 0))
        require(payable >= 0, 'El ajuste produce un importe negativo.')
        contingency_limit = rules.get('contingency_limit')
        if contingency_limit is not None:
            contingency_full = sum(money(decimal(l['quantity']) * decimal(l['unit_price'])) for l in catalog if l.get('kind') == 'imprevisto')
            require(contingency_full <= decimal(contingency_limit), 'Rubros imprevistos superan la reserva contractual.')
        return {'lines': rows, 'groups': {k: str(v) for k, v in groups.items()}, 'base': str(base), 'iva': str(vat), 'social': str(social), 'social_payment': social_payment, 'icc_base': str(eligible), 'icc_initial': initial, 'icc_current': icc_current, 'adjustment': str(adjustment), 'adjustment_iva': str(adjustment_vat), 'payable': str(payable), 'contract_base': str(full), 'rules': rules, 'rounding': 'Decimal 40 dígitos; moneda 2 decimales ROUND_HALF_UP; avances 8 decimales'}
