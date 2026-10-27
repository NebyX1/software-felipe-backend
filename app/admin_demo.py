from flask import Blueprint, redirect, render_template_string, abort, current_app
from flask_login import current_user
from .models import User
from .models.domain import Intervention, Company, History

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.get('/login')
def login():
    return redirect('/login')


@admin_bp.get('/')
@admin_bp.get('/dashboard')
def dashboard():
    if not current_user.is_authenticated:
        return redirect('/login')
    if not current_user.is_admin or (current_user.demo and not current_app.config['DEMO_AUTH_ENABLED']):
        abort(403)
    return render_template_string('''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Administración · Obras Lavalleja</title><style>body{font:16px system-ui;background:#f3f6fa;color:#173149;margin:0}main{max-width:1000px;margin:50px auto;padding:24px}a{color:#146a89}.cards{display:flex;gap:24px;flex-wrap:wrap}.cards p{background:white;padding:24px;border-radius:12px}</style><main><small>ENTORNO DE DEMOSTRACIÓN</small><h1>Administración de Obras</h1><p>{{ user.name }}</p><div class="cards"><p>{{ works }} intervenciones</p><p>{{ companies }} empresas</p><p>{{ users }} usuarios</p><p>{{ events }} acciones auditadas</p></div><p><a href="/administracion">Gestionar empresas, profesionales, equipos y catálogos</a></p><p><a href="/">Volver al panel de obras</a></p></main></html>''', user=current_user, works=Intervention.query.count(), companies=Company.query.count(), users=User.query.count(), events=History.query.count())
