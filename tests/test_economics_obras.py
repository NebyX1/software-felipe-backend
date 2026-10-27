from decimal import Decimal
import pytest
from app.services.economics import calculate
from app.services.errors import DomainError

def line(code='1',qty='10',price='200',social='0',kind='basico'):
    return dict(code=code,description='Fixture independiente',unit='m2',quantity=qty,unit_price=price,social_rate=social,kind=kind,icc_eligible=True)
RULES={'iva_rate':'0.22','social_payment':'separado'}

def test_molino_icc_periodo_independent():
    # Base 2000 * 25% =500, ICC 110/100-1=10%, IVA 110+11.
    c=calculate([line()],{'1':'25'},{},{**RULES,'icc_initial':'100'},'periodo','110')
    assert (c['base'],c['adjustment'],c['iva'],c['adjustment_iva'],c['payable'])==('500.00','50.00','110.00','11.00','671.00')
    assert c['lines'][0]['accumulated']=='0.25000000'

def test_bulevar_cumulative_and_social():
    # Period is 60%-25%=35%; 2000*.35=700; social700*.121=84.70.
    c=calculate([line(social='0.121')],{'1':'60'},{'1':'0.25'},RULES,'acumulado')
    assert (c['base'],c['social'],c['payable'])==('700.00','84.70','854.00')
    assert c['lines'][0]['period']=='0.35000000'

@pytest.mark.parametrize('mode,value',[('cantidad','2.5'),('importe','500'),('periodo','25'),('acumulado','25')])
def test_equivalent_modes(mode,value):
    assert calculate([line()],{'1':value},{},RULES,mode)['base']=='500.00'

def test_missing_accumulated_keeps_previous():
    c=calculate([line()],{}, {'1':'.5'},RULES,'acumulado')
    assert c['base']=='0.00' and c['lines'][0]['accumulated']=='0.50000000'

@pytest.mark.parametrize('value',['101','-1','NaN','Infinity'])
def test_invalid_values(value):
    with pytest.raises(DomainError):calculate([line()],{'1':value},{},RULES,'periodo')

def test_regression_and_over_contract():
    for mode,value in [('periodo','70'),('acumulado','10'),('cantidad','7')]:
        with pytest.raises(DomainError):calculate([line()],{'1':value},{'1':'.5'},RULES,mode)

def test_contingencies_extensions_rounding():
    c=calculate([line('A','1','0.05'),line('I','1','100','0.13','imprevisto'),line('X','1','200','0.08','ampliacion')],{'A':'50','I':'100','X':'100'},{},{**RULES,'social_payment':'incluido','contingency_limit':'100'},'periodo')
    assert c['base']=='300.03' and c['social']=='29.00' and c['payable']=='395.04'
    assert c['groups']=={'basico':'0.03','imprevisto':'100.00','ampliacion':'200.00'}
    with pytest.raises(DomainError):calculate([line(kind='imprevisto')],{}, {},{**RULES,'contingency_limit':'10'},'periodo')
