import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import URL

_BASE_DIR = Path(__file__).resolve().parent.parent
_DOTENV_PATH = _BASE_DIR / '.env'

# Load backend/.env when present without overriding injected env vars.
load_dotenv(_DOTENV_PATH, override=False)


def database_uri(environment=None):
    values = os.environ if environment is None else environment
    # Compose passes credentials separately so symbols never corrupt a URL.
    if values.get('DATABASE_HOST'):
        return URL.create('mysql+pymysql', username=values.get('DATABASE_USER', 'obras'),
            password=values.get('DATABASE_PASSWORD', ''), host=values['DATABASE_HOST'],
            port=int(values.get('DATABASE_PORT', '3306')), database=values.get('DATABASE_NAME', 'obras_demo'),
            query={'charset': 'utf8mb4'}).render_as_string(hide_password=False)
    return values.get('DATABASE_URL') or values.get('DATABASE_URI') or 'sqlite:///gvl.db'

# ─────────────────────────────────────────────────────────────────────────────
# CivicFlow – Plataforma de Gestión Pública · IDL
# ─────────────────────────────────────────────────────────────────────────────


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _parse_csv(
    value: str | None,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    if not value:
        return fallback
    parsed = tuple(
        item.strip().lower()
        for item in value.split(',')
        if item.strip()
    )
    return parsed or fallback


def _normalize_origin(value: str | None) -> str:
    if not value:
        return ''
    return value.strip().strip('"').strip("'").rstrip('/')


def _parse_cors_origins(
    raw_value: str | None,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    candidates = raw_value.split(',') if raw_value else fallback
    normalized: list[str] = []
    seen: set[str] = set()

    for item in candidates:
        origin = _normalize_origin(item)
        if not origin:
            continue
        key = origin.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(origin)

    return tuple(normalized) or fallback


class Config:
    # Authorization reads occur before resource locks. READ COMMITTED ensures
    # a waiting transaction sees the winner's newly committed certificate.
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping':True,'pool_recycle':300,'isolation_level':'READ COMMITTED'}
    ENV_NAME = (os.environ.get('FLASK_ENV') or 'production').strip().lower()
    SECRET_KEY = (
        os.environ.get('SECRET_KEY')
        or 'change-me-in-production-please'
    )
    SQLALCHEMY_DATABASE_URI = database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)
    JWT_TOKEN_LOCATION = ['headers']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'

    # Mail
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False') == 'True'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = (
        os.environ.get('MAIL_DEFAULT_SENDER')
        or 'noreply@gvl.local'
    )

    # App identity
    APP_NAME = os.environ.get('APP_NAME', 'Lavalleja · Gestión de obras')
    FRONTEND_URL = _normalize_origin(
        os.environ.get('FRONTEND_URL')
    )

    # WTF / CSRF (admin HTML panel)
    WTF_CSRF_SECRET_KEY = os.environ.get('WTF_CSRF_SECRET_KEY') or SECRET_KEY

    # Session security (admin HTML panel uses server-side sessions)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = not _as_bool(
        os.environ.get('FLASK_DEBUG'),
        default=False,
    )
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour admin session

    # Redis (optional – for rate limiting)
    REDIS_URL = os.environ.get('REDIS_URL') or 'memory://'
    RATELIMIT_STORAGE_URI = (
        os.environ.get('RATELIMIT_STORAGE_URI')
        or REDIS_URL
    )

    # CORS – origins loaded exclusively from env vars; no hardcoded fallback.
    # CORS validates the request *origin*, not the backend path.
    # Flask-CORS is initialized globally so every endpoint is covered.
    CORS_ORIGINS_RAW = os.environ.get('CORS_ORIGINS')
    _frontend_fallback = (FRONTEND_URL,) if FRONTEND_URL else ()
    CORS_ALLOWED_ORIGINS = list(
        _parse_cors_origins(CORS_ORIGINS_RAW, _frontend_fallback)
    )
    CORS_ALLOW_HEADERS = (
        'Authorization',
        'Content-Type',
        'X-Requested-With',
    )
    CORS_METHODS = (
        'GET',
        'POST',
        'PUT',
        'PATCH',
        'DELETE',
        'OPTIONS',
    )
    CORS_SUPPORTS_CREDENTIALS = True

    # Works module files
    WORKS_UPLOAD_DIR = (
        os.environ.get('WORKS_UPLOAD_DIR')
        or os.path.join(os.getcwd(), 'uploads', 'works')
    )
    WORKS_ALLOWED_DOCUMENT_MIME_TYPES = _parse_csv(
        os.environ.get('WORKS_ALLOWED_DOCUMENT_MIME_TYPES'),
        (
            'application/pdf',
            'application/msword',
            (
                'application/vnd.openxmlformats-'
                'officedocument.wordprocessingml.document'
            ),
            'application/vnd.ms-excel',
            (
                'application/vnd.openxmlformats-'
                'officedocument.spreadsheetml.sheet'
            ),
            'text/plain',
        ),
    )
    WORKS_ALLOWED_IMAGE_MIME_TYPES = _parse_csv(
        os.environ.get('WORKS_ALLOWED_IMAGE_MIME_TYPES'),
        (
            'image/webp',
            'image/jpeg',
            'image/png',
            'image/gif',
        ),
    )
    WORKS_ALLOWED_MIME_TYPES = (
        WORKS_ALLOWED_DOCUMENT_MIME_TYPES
        + WORKS_ALLOWED_IMAGE_MIME_TYPES
    )
    WORKS_MAX_FILE_SIZE = int(
        os.environ.get('WORKS_MAX_FILE_SIZE')
        or 2 * 1024 * 1024
    )





