# Verificación del despliegue separado

Fecha: 2026-10-27. Origen: `NebyX1/software-gestion-obras`, commit `5293894`.

Las verificaciones se ejecutaron localmente con Docker Linux y dos proyectos Compose separados. No se realizó un despliegue en una instancia de Coolify.

| Comprobación | Resultado |
| --- | --- |
| Construcción independiente de frontend, backend y MinIO | Aprobada |
| Lint, TypeScript y compilación Vite | Aprobados |
| Dependencias Python (`pip check`) | Sin conflictos |
| Pruebas de backend, con MariaDB y MinIO reales | 64 aprobadas |
| Navegador: escritorio y móvil | 34 aprobadas |
| Migraciones, bucket privado y primera carga automática | Aprobados |
| Salud de MariaDB, Redis, MinIO y API | Correcta |
| Proxy HTTPS, SNI, Host y certificado confiable | Aprobados |
| Certificado de backend sin confianza | Rechazado correctamente |
| Salud del frontend sin backend disponible | Correcta |
| Origen de backend con ruta incorrecta | Rechazado al iniciar |
| Recarga de rutas React y errores JSON de API | Correctos |
| Descargas y enlaces temporales | SHA-256 verificado |
| Recreación del backend y repetición del bootstrap | 17 intervenciones y 56 documentos de prueba conservados, sin cambios de versiones ni huellas |
| Secretos, entornos y material privado en archivos a publicar | Comprobación aprobada |

Los escenarios de navegador incluyen los nueve perfiles, guía, altas de intervención, tramitación documental, subsanación, bandeja, mapas, GeoJSON público, anotación y nueva versión de PDF, contratos, certificación y pagos ficticios de ambas empresas. Las pruebas de backend utilizan exclusivamente el esquema `obras_test` y un bucket independiente.

La prueba HTTPS usa una autoridad temporal privada para representar el ingreso TLS de un backend desplegado aparte. La imagen del frontend verifica el certificado; no se desactivó esa validación. Los certificados de prueba, claves, entornos, base de datos y archivos generados permanecen fuera de los repositorios publicados.

Las imágenes finales se reconstruyeron con los archivos de distribución. Se mantuvieron los avisos no bloqueantes del compilador sobre tamaño de bundles y comentarios de una dependencia. No impiden construir ni iniciar la aplicación.

Para instalar en Coolify, seguir el README de cada repositorio: backend con Docker Compose y frontend con Dockerfile. Es necesario asignar los dominios reales y conectar `FRONTEND_URL` con `BACKEND_URL`. Los workflows incluidos vuelven a comprobar cada repositorio en GitHub Actions.
