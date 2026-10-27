from app.services.economics import calculate
from decimal import Decimal

def test_quantities_thirds_settle_exact_contract_balance():
    line={'code':'1','quantity':'3','unit_price':'33.33333333','social_rate':'0.121','kind':'basico','icc_eligible':True}
    previous={};quantities={};base=Decimal(0);social=Decimal(0)
    for period in range(3):
        result=calculate([line],{'1':'1'},previous,{'iva_rate':'0','social_payment':'separado'},'cantidad',previous_quantities=quantities)
        base+=Decimal(result['base']);social+=Decimal(result['social']);previous['1']=result['lines'][0]['accumulated']
        quantities['1']=result['lines'][0]['accumulated_quantity']
    assert base==Decimal('100.00') and social==Decimal('12.10') and previous['1']=='1.00000000'
