"""Only create/grant the dedicated MariaDB test schema, using container secrets."""
import subprocess
from pathlib import Path
command='exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e "CREATE DATABASE IF NOT EXISTS obras_test CHARACTER SET utf8mb4; GRANT ALL ON obras_test.* TO \'obras\'@\'%\';"'
result=subprocess.run(['docker','compose','exec','-T','db','sh','-c',command],cwd=Path(__file__).resolve().parents[1])
if result.returncode:raise SystemExit(result.returncode)
print('obras_test preparado. No se modificó obras_demo.')
