"""Create private local Compose secrets once; never print them."""
import argparse
from pathlib import Path
import secrets
from urllib.parse import urlsplit

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--frontend-url', required=True)
args = parser.parse_args()
url = urlsplit(args.frontend_url)
if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
    parser.error('Usá el origen del frontend sin rutas ni credenciales.')
target = root / '.env'
if target.exists():
    print('.env existente conservado; editá FRONTEND_URL si cambió el dominio.')
else:
    values = {'FRONTEND_URL': args.frontend_url.rstrip('/'),
        'SERVICE_PASSWORD_DBPASSWORD': secrets.token_urlsafe(36), 'SERVICE_PASSWORD_DBROOT': secrets.token_urlsafe(36),
        'SERVICE_PASSWORD_64_SESSION': secrets.token_urlsafe(48), 'SERVICE_PASSWORD_64_JWT': secrets.token_urlsafe(48),
        'SERVICE_USER_MINIO': 'obras-' + secrets.token_hex(8), 'SERVICE_PASSWORD_64_MINIO': secrets.token_urlsafe(48),
        'SERVICE_PASSWORD_DEMOACCESS': secrets.token_urlsafe(18)}
    with target.open('x', encoding='utf-8') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    print('.env privado creado. No subirlo al repositorio.')
