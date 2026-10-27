from flask import Blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')
from . import identity, interventions, documents, certificates, imports, administration, assistant, workflow, companies, checkout  # noqa: E402,F401
