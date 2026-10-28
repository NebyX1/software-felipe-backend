"""Serialized migration, private bucket and one-time demo initialization."""
import os
import sys
from pathlib import Path
from flask_migrate import upgrade
from sqlalchemy import text
from minio.versioningconfig import VersioningConfig, ENABLED
from app import create_app
from app.extensions import db
from app.models import User
from app.models.domain import DemoInstallation
from app.demo import seed
from app.infrastructure.storage import get_document_storage

SEED_VERSION = 'director-demo-v1'


def initialize(app=None, seed_demo=True, initialize_storage=True):
    app = app or create_app()
    with app.app_context(), db.engine.connect() as lock:
        name = db.engine.url.database + ':bootstrap'
        if lock.execute(text('SELECT GET_LOCK(:name, 120)'), {'name': name}).scalar() != 1:
            raise RuntimeError('Otra instancia sigue inicializando la base. Reintentá el despliegue.')
        lock.commit()
        try:
            print('Aplicando migraciones...', flush=True)
            upgrade(directory=str(Path(__file__).resolve().parent / 'migrations'))
            if initialize_storage or seed_demo:
                storage = get_document_storage()
                if not storage.client.bucket_exists(storage.bucket):
                    storage.client.make_bucket(storage.bucket)
                storage.client.set_bucket_versioning(storage.bucket, VersioningConfig(ENABLED))
            if not seed_demo:
                return
            if not (app.config['DEMO_AUTH_ENABLED'] and app.config['DEMO_ENVIRONMENT']):
                raise RuntimeError('La carga sintética requiere ambos modos de demo habilitados.')
            marker = DemoInstallation.query.filter_by(seed_version=SEED_VERSION).first()
            if not marker:
                # Existing installations only migrate: keep all operator changes intact.
                state = 'ready' if User.query.first() else 'initializing'
                marker = DemoInstallation(seed_version=SEED_VERSION, state=state)
                db.session.add(marker)
                db.session.commit()
            if marker.state == 'initializing':
                print('Preparando cuentas y escenarios ficticios de la primera instalación...', flush=True)
                seed()
                marker.state = 'ready'
                db.session.commit()
            print('Instalación preparada. Los siguientes arranques conservan los datos.', flush=True)
        finally:
            db.session.rollback()
            lock.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': name})
            lock.commit()


if __name__ == '__main__':
    try:
        demo = os.getenv('DEMO_SEED_ON_START', 'false').lower() == 'true'
        initialize(seed_demo=demo, initialize_storage=os.getenv('INIT_BUCKET_ON_START', 'true' if demo else 'false').lower() == 'true')
    except Exception as error:
        print(f'No se pudo preparar la instalación ({type(error).__name__}). Revisá la configuración y los servicios internos; no borres volúmenes.', file=sys.stderr)
        raise SystemExit(1)
