# Software Felipe · Backend de Gestión de Obras

API Flask independiente, con MariaDB, Redis y MinIO privado. Código de origen: `NebyX1/software-gestion-obras`, commit `5293894`. Frontend complementario: [software-felipe-frontend](https://github.com/NebyX1/software-felipe-frontend).

## Desplegar en Coolify

1. Crear una aplicación desde este repositorio, rama **main**.
2. Seleccionar **Docker Compose**, directorio base `/`, archivo **`compose.coolify.yaml`**.
3. Definir `FRONTEND_URL=https://obras.tudominio.com`, sin rutas ni barra final. Debe ser el dominio público del frontend.
4. Asignar `https://api-obras.tudominio.com` exclusivamente al servicio **backend**, puerto interno **5000**. No publicar MariaDB, Redis ni MinIO.
5. Desplegar. Coolify genera los secretos `SERVICE_PASSWORD_*` y `SERVICE_USER_MINIO`; el arranque espera los servicios, aplica las migraciones, crea el bucket privado y carga los ejemplos de forma idempotente. La primera construcción de MinIO puede demorar varios minutos.
6. Verificar `https://api-obras.tudominio.com/api/health/ready`: HTTP 200 con base, almacenamiento y Redis disponibles.
7. En el frontend configurar `BACKEND_URL=https://api-obras.tudominio.com` como variable de ejecución.

El código privado de ingreso de la demo se obtiene de `SERVICE_PASSWORD_DEMOACCESS` en Coolify. También se puede definir `DEMO_ACCESS_CODE` propio, de al menos 8 caracteres. No queda publicado en Git ni incorporado al frontend.

Los volúmenes `obras-db`, `obras-redis` y `obras-objects` conservan los datos entre despliegues. No eliminarlos al actualizar. El bootstrap se serializa con un bloqueo de MariaDB y conserva los cambios de las instalaciones existentes. Usar una instalación separada de cualquier proyecto anterior.

## Configuración

| Variable | Uso |
| --- | --- |
| `FRONTEND_URL` | Origen público del frontend; también configura CORS. |
| `DEMO_ACCESS_CODE` | Sobrescribe el código privado generado por Coolify. |
| `DB_PASSWORD`, `DB_ROOT_PASSWORD` | Sobrescriben los secretos generados para la base. |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Sobrescriben los secretos de sesión y token. Mantenerlos entre reinicios. |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | Sobrescriben las credenciales privadas de MinIO. |
| `AI_ENABLED`, `OLLAMA_API_KEY`, `OLLAMA_MODEL` | IA opcional, desactivada por defecto; claves sólo aquí. |

El archivo Compose ya configura HTTPS detrás de proxy, cookies seguras, salud con tiempo de arranque suficiente y almacenamiento privado. Los puertos de los servicios no se publican al host.

## Construcción y prueba local

Requisitos: Docker con Compose v2.24+ y Python 3.11+.

```sh
python scripts/configure.py --frontend-url http://127.0.0.1:18088
docker compose up -d --build --wait --wait-timeout 300
python scripts/prepare_tests.py
docker compose exec -T backend python -m pytest tests -q
```

El archivo `.env` local contiene secretos aleatorios, queda ignorado por Git y no se copia a la imagen. Para pruebas, `prepare_tests.py` crea exclusivamente el esquema `obras_test`; las integraciones verifican ese nombre antes de limpiar datos. La API no tiene puerto publicado por defecto: usar un proxy en la red Docker o un override de Compose para desarrollo.

## Alcance

Demo institucional con datos sintéticos, perfiles y pagos DemoPay. No mueve fondos ni sustituye las integraciones de identidad, firma o banco reales. Documentación: [API](docs/API.md), [reglas](docs/BUSINESS_RULES.md), [integraciones](docs/INTEGRATIONS.md) y [preparación institucional](docs/PRODUCTION_READINESS.md).

## Verificación de entrega

[Resultados de construcción, pruebas y persistencia](VERIFICACION.md).
