"""Explicit boundaries, replaced independently of the internal business cycle."""
from typing import Protocol
from uuid import uuid4

class DossierPort(Protocol):
    def register(self,certificate_id:int)->dict:...
class SignaturePort(Protocol):
    def acknowledge(self,actor_id:int,resource:str)->dict:...
class PaymentPort(Protocol):
    def confirm(self,actor_id:int,reference:str)->dict:...

class DemoInstitutionalAdapter:
    def register(self,certificate_id):
        return {'reference':f'DEMO-PAGO-{certificate_id:06d}','origin':'simulacion_interna','official':False}
    def acknowledge(self,actor_id,resource):
        return {'id':'DEMO-APROBACION-'+uuid4().hex,'actor_id':actor_id,'resource':resource,'institutional_signature':False}
    def confirm(self,actor_id,reference):
        return {'reference':reference,'actor_id':actor_id,'fictitious':True,'bank_transfer':False}
