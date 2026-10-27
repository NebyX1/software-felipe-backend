"""Audit distributable files without printing credentials. No third-party dependencies."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def env_values(path):
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true', help='Scan the exact bytes in the Git index.')
    args = parser.parse_args()
    config = env_values(ROOT / '.env')
    private_paths = [p for base in (ROOT, ROOT / 'backend', ROOT / 'frontend') for p in base.glob('.env*') if p.name != '.env.example']
    if config.get('AI_ENV_FILE'):
        private_paths.append(ROOT / config['AI_ENV_FILE'])
    private_values = set()
    # Published legacy development defaults are not private credentials.
    # New installations generate unique replacements; provider/session keys never bypass this check.
    public_demo_defaults = {'obras-' + suffix for suffix in ('local-demo', 'root-demo', 'minio-demo-private', 'demo')}
    for env in private_paths:
        for key, value in env_values(env).items():
            if key in ('DB_PASSWORD', 'DB_ROOT_PASSWORD', 'MINIO_SECRET_KEY', 'MINIO_ACCESS_KEY') and value in public_demo_defaults:
                continue
            if (any(term in key for term in ('KEY', 'SECRET', 'PASSWORD', 'TOKEN')) or key == 'DEMO_ACCESS_CODE') and len(value) >= 8:
                private_values.add(value.encode())
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths = [path for path in paths if path]
    if not paths:
        print('No distributable files found. Stage files before using --staged.', file=sys.stderr)
        return 1
    failures = []
    token_pattern = re.compile(rb'(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    for name in paths:
        path = Path(name)
        if path.parts[0] in ('sample', 'documents', 'backups', 'tmp', 'private-data') or (path.name.startswith('.env') and path.name != '.env.example') or path.suffix.lower() in ('.sql', '.db', '.sqlite', '.sqlite3', '.pem', '.key', '.p12', '.pfx'):
            failures.append({'file': name, 'reason': 'private/generated path'})
            continue
        content = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT) if args.staged else (ROOT / name).read_bytes()
        if any(value in content for value in private_values) or token_pattern.search(content):
            failures.append({'file': name, 'reason': 'credential detected (value withheld)'})
    print(json.dumps({'status': 'failed' if failures else 'verified', 'files_scanned': len(paths), 'source': 'git index' if args.staged else 'tracked files', 'secret_values_printed': False, 'failures': failures}))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
