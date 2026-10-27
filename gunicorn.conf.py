"""
Gunicorn configuration for CivicFlow production deployment.
All values can be overridden via environment variables.
"""
import os


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# Server socket
bind = f"0.0.0.0:{_int_env('PORT', 5000)}"

# Worker configuration
workers = _int_env("GUNICORN_WORKERS", 4)
worker_class = "gthread"
threads = _int_env("GUNICORN_THREADS", 2)

# Timeouts
timeout = _int_env("GUNICORN_TIMEOUT", 60)
graceful_timeout = _int_env("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _int_env("GUNICORN_KEEPALIVE", 5)

# Worker recycling (prevents memory leaks)
max_requests = _int_env("GUNICORN_MAX_REQUESTS", 1000)
max_requests_jitter = _int_env("GUNICORN_MAX_REQUESTS_JITTER", 100)

# Tmp directory on RAM for better performance
worker_tmp_dir = "/dev/shm"

# Logging — stdout/stderr for Docker/Coolify log collector
accesslog = "-"
access_log_format = '%(h)s %(m)s %(s)s %(b)s %(D)s'
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True

# Do not load app code before forking workers (avoids SQLAlchemy issues)
preload_app = False

# Trust Coolify's Traefik proxy headers
forwarded_allow_ips = "*"
