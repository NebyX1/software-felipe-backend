import pytest
from pydantic import ValidationError
from app.ai import provider

def test_mapping_schema_rejects_invented_business_fields_and_renamed_headers(monkeypatch):
    headers=['Código','Descripción']
    monkeypatch.setattr(provider,'_config',lambda:{})
    async def mock_bounded(config,schema,prompt):
        # These model mistakes were observed at the real cloud boundary.
        with pytest.raises(ValidationError):schema.model_validate({'mapping':{'approve':'Código'},'issues':[]})
        with pytest.raises(ValidationError):schema.model_validate({'mapping':{'code':'Codigo'},'issues':[]})
        return schema.model_validate({'mapping':{'code':'Código','description':'Descripción'},'issues':['Revisión humana requerida.']})
    monkeypatch.setattr(provider,'_bounded',mock_bounded)
    result=provider.propose_mapping(headers)
    assert result['mapping']=={'code':'Código','description':'Descripción'}
