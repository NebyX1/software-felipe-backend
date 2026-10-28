# Verificación de la arquitectura institucional y MariaDB

Fecha: 2026-10-28. Referencia: [NebyX1/buzon-ciudadano-backend](https://github.com/NebyX1/buzon-ciudadano-backend), commit `4a12395`.

## Configuración corregida

- `DATABASE_URL` se transmite íntegra a SQLAlchemy con el prefijo `mariadb+mariadbconnector://`. Se admite `SQLALCHEMY_DATABASE_URI` como alias cuando falta `DATABASE_URL`, igual que en la referencia.
- Los fragmentos `DATABASE_HOST`, `DATABASE_USER`, `DATABASE_PASSWORD` y `DATABASE_NAME` ya no reconstruyen ni sustituyen la URL de producción. No existe una base SQLite implícita.
- Se usa MariaDB Connector/Python `mariadb==1.1.14`. PyMySQL se retiró de las dependencias y se comprobó su ausencia en la imagen final.
- Factory `create_app(config_name)`, perfiles `development`, `production` y `testing`, extensiones separadas y parámetros de pool de la referencia. Se conserva el aislamiento `READ COMMITTED` exigido por las reglas de certificación y pagos.
- El despliegue institucional es un contenedor backend con MariaDB, MinIO y Redis configurados externamente. `compose.coolify.yaml` contiene sólo el servicio backend; `compose.test.yaml` se reserva para infraestructura local/CI.
- Las migraciones se ejecutan antes de Gunicorn. La inicialización del bucket y la carga de demo son opciones independientes.

## Resultados

| Comprobación | Resultado |
| --- | --- |
| Construcción de la imagen Python 3.11 con bibliotecas MariaDB nativas | Aprobada |
| Controlador SQLAlchemy real | `mariadbconnector` |
| Módulo DBAPI real | `mariadb` |
| Consulta al servidor | `11.4.5-MariaDB-ubu2404` |
| Aislamiento real de la conexión | `READ-COMMITTED` |
| Dependencias Python (`pip check`) | Sin conflictos |
| Suite de backend con MariaDB y MinIO reales | 79 pruebas aprobadas |
| Navegador en escritorio y móvil | 34 pruebas aprobadas |
| Manifiesto institucional con servicios externos | Sólo `backend`; arranque saludable y consultas reales correctas |
| Perfiles de Flask, cookies y prioridad de URL | Aprobados |
| URL inválida y errores de configuración | Rechazo sin exponer credenciales |
| Migraciones sin inicializar almacenamiento | Aprobadas |
| Actualización de la instalación anterior | 17 intervenciones y 56 documentos conservados con los mismos IDs, versiones y huellas |
| Recreación con el conector nativo tras las pruebas | 29 intervenciones y 86 documentos conservados sin cambios |
| Descargas y enlaces temporales a través del proxy HTTPS | SHA-256 correcto |

Las pruebas funcionales cubren los nueve perfiles, tramitación, subsanación, mapas, PDFs, contratos, certificaciones y pagos ficticios. Las integraciones de backend utilizan exclusivamente el esquema reservado `obras_test` y un bucket de prueba; no utilizan la base del Buzón Ciudadano.

Las comprobaciones se ejecutaron localmente con Docker Linux, incluida una instalación independiente del backend usando el manifiesto de producción y una MariaDB accesible por la URL suministrada. No se realizó un despliegue en la instancia de Coolify del usuario. El workflow de GitHub Actions reproduce las pruebas con el conector nativo y una infraestructura de CI separada.

La receta de despliegue, las variables completas y el formato de conexión están en [README.md](README.md) y [.env.example](.env.example). Los entornos privados, claves y archivos generados permanecen excluidos de Git y de la imagen.
