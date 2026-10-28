"""Generate isolated local/CI infrastructure in .env.test; never edit production .env."""
import argparse
from pathlib import Path
import secrets
from urllib.parse import quote, urlsplit

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--frontend-url', default='http://127.0.0.1:18088')
args = parser.parse_args()
url = urlsplit(args.frontend_url)
if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
    parser.error('Usá el origen del frontend sin rutas ni credenciales.')
target = root / '.env.test'
if target.exists():
    print('.env.test existente conservado. La configuración de producción no se modifica.')
else:
    password = secrets.token_urlsafe(36)
    values = {
        'DATABASE_URL': f'mariadb+mariadbconnector://obras:{quote(password, safe="")}@db:3306/obras_demo',
        'FRONTEND_URL': args.frontend_url.rstrip('/'),
        'SERVICE_PASSWORD_DBPASSWORD': password,
        'SERVICE_PASSWORD_DBROOT': secrets.token_urlsafe(36),
        'SERVICE_PASSWORD_64_SESSION': secrets.token_urlsafe(48),
        'SERVICE_PASSWORD_64_JWT': secrets.token_urlsafe(48),
        'SERVICE_USER_MINIO': 'obras-' + secrets.token_hex(8),
        'SERVICE_PASSWORD_64_MINIO': secrets.token_urlsafe(48),
        'SERVICE_PASSWORD_DEMOACCESS': secrets.token_urlsafe(18),
    }
    with target.open('x', encoding='utf-8') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    print('.env.test privado creado para compose.test.yaml. No subirlo al repositorio.')
