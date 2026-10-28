# Software Felipe · Backend de Gestión de Obras

Backend modular Flask con factory, extensiones separadas, SQLAlchemy, migraciones Alembic, blueprints por dominio y servicios de negocio. La configuración institucional sigue [buzon-ciudadano-backend](https://github.com/NebyX1/buzon-ciudadano-backend), referencia revisada en el commit `4a12395`.

Frontend: [software-felipe-frontend](https://github.com/NebyX1/software-felipe-frontend).

## Conexión institucional a MariaDB

Se utiliza **MariaDB Connector/Python**, paquete `mariadb==1.1.14`, y una única URL completa:

```dotenv
DATABASE_URL=mariadb+mariadbconnector://root:password@localhost:3306/software_felipe
```

El formato es el mismo del ejemplo institucional `mariadb+mariadbconnector://root:password@localhost:3306/buzon-ciudadano`; el nombre final identifica la base de este proyecto. La aplicación toma `DATABASE_URL` literalmente. Como la referencia, admite `SQLALCHEMY_DATABASE_URI` cuando no se define `DATABASE_URL`.

La base debe existir en el servidor MariaDB configurado. No se crea una base adicional de producción desde Compose. No se reconstruye la URL a partir de `DATABASE_HOST` u otras variables separadas y no hay una base SQLite implícita. El arranque verifica que el controlador sea `mariadb+mariadbconnector`.

Si la contraseña contiene caracteres reservados de URL, deben estar codificados: por ejemplo, `@` como `%40`. La URL completa y las credenciales se guardan en `.env` o en las variables privadas de Coolify.

## Arquitectura y configuración

- `app/config.py`: `Config`, `DevelopmentConfig`, `ProductionConfig`, `TestingConfig` y registro de perfiles.
- `app/__init__.py`: `create_app(config_name)` e inicialización de extensiones con `init_app`.
- `app/extensions.py`: SQLAlchemy, Flask-Migrate, autenticación, correo y controles compartidos sin instancia Flask vinculada.
- `app/api/`, `app/services/` y `app/models/`: endpoints por dominio, reglas de negocio y ORM.
- `migrations/`: historial de migraciones; `bootstrap.py` serializa su aplicación y la primera carga opcional.
- `wsgi.py`, `gunicorn.conf.py` y `entrypoint.sh`: entrada independiente de producción.

El pool sigue los parámetros de la referencia: `pool_pre_ping`, reciclado de 1800 segundos, timeout de 30, tamaño de 10 y overflow de 20. Se conserva `READ COMMITTED`, necesario para las operaciones concurrentes de certificación y pagos.

## Desplegar en Coolify

1. Crear una aplicación desde este repositorio, rama **main**, tipo **Dockerfile**, directorio base `/`, archivo `/Dockerfile`, puerto interno **5000**. También se incluye `compose.coolify.yaml`, con un único servicio backend y servidores de datos externos.
2. Asignar el dominio HTTPS del backend.
3. Cargar las variables de `.env.example` con los valores reales: `DATABASE_URL`, `SECRET_KEY`, el origen del frontend y el acceso a MinIO. `JWT_SECRET_KEY` puede configurarse aparte o heredar `SECRET_KEY`.
4. En `DATABASE_URL`, usar el hostname o IP de la MariaDB accesible desde el contenedor. `localhost` es correcto cuando Flask y MariaDB corren directamente en el mismo equipo; dentro de Docker identifica el propio contenedor. El prefijo sigue siendo exactamente `mariadb+mariadbconnector://`.
5. Para usar la demo de obras, habilitar las variables `DEMO_*` del ejemplo, definir un `DEMO_ACCESS_CODE` privado de al menos 8 caracteres y activar `DEMO_SEED_ON_START=true` e `INIT_BUCKET_ON_START=true`. La carga inicial es idempotente y preserva los datos existentes.
6. Desplegar. El contenedor aplica las migraciones antes de iniciar Gunicorn. `/health` comprueba el proceso; `/api/health/ready` comprueba la conexión real a MariaDB, el bucket y Redis cuando se configura.
7. En el frontend conservar `BACKEND_URL=https://api-obras.tudominio.com` como variable de ejecución.

MariaDB y MinIO son servicios configurados por el entorno, igual que en el backend de referencia. Redis es opcional; `REDIS_URL` permite conectar la instancia institucional. Las credenciales existentes se mantienen fuera de Git y de las imágenes. Un error de migración detiene el arranque y no se modifica el historial para ocultarlo.

La inicialización del bucket y la carga de demo se controlan por separado de las migraciones. Con `INIT_BUCKET_ON_START=false` y `DEMO_SEED_ON_START=false` el arranque aplica solamente las migraciones de la base configurada.

Para actualizar una instalación existente, configurar la URL de la base de obras que ya contiene sus datos con el nuevo prefijo y conservar las credenciales y los volúmenes de esa instalación. Si se utilizó la receta anterior con servicios incluidos, mantener esos servicios de datos disponibles al pasar al despliegue independiente. Esta corrección conserva los modelos y el historial de migraciones.

## Desarrollo local

Copiar `.env.example` a `.env`, completar las credenciales y seleccionar `FLASK_CONFIG=development`.

```sh
python -m venv venv
# Windows: venv/Scripts/python.exe; Linux: venv/bin/python
venv/Scripts/python.exe -m pip install -r requirements.lock
venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe wsgi.py
```

## Pruebas aisladas

`compose.test.yaml` contiene infraestructura exclusiva de desarrollo/CI, separada del despliegue institucional. El generador escribe únicamente `.env.test`; nunca sobrescribe `.env`.

```sh
python scripts/configure.py --frontend-url http://127.0.0.1:18088
docker compose --env-file .env.test -f compose.test.yaml up -d --build --wait --wait-timeout 300
python scripts/prepare_tests.py
docker compose --env-file .env.test -f compose.test.yaml exec -T backend python -m pytest tests -q
```

Las integraciones verifican el nombre reservado `obras_test` antes de limpiar tablas y utilizan un bucket de prueba separado. Se comprueba el controlador DBAPI real, una consulta MariaDB, el aislamiento de transacciones, los perfiles y la prioridad de `DATABASE_URL`.

[Resultados de verificación](VERIFICACION.md). [API](docs/API.md), [reglas](docs/BUSINESS_RULES.md) e [integraciones](docs/INTEGRATIONS.md).
