# Preparación para producción y alcance de la demo

La aplicación corre localmente con MariaDB, Redis, MinIO privado/versionado, Gunicorn y Nginx. Se ampliaron pagos, trámites, avisos, representación empresarial y fichas. Los resultados ejecutados se registran en TEST_REPORT.md. La demo permite mostrar procesos completos con datos sintéticos; no acredita homologación institucional.

## Componentes disponibles

- Estados y versiones controlados en servidor; cálculos monetarios Decimal; aprobaciones con instantáneas y ledger acumulado.
- Alcance por obra/empresa, evidencia privada, representación validada/vigente y revocación de sesión; denegaciones auditadas después del rollback.
- Documentos originales privados, hash de integridad, versiones y preservación de evidencia de certificados/pagos/trámites.
- Pago electrónico interno simulado con concurrencia/idempotencia/reintentos, comprobante y desactivación fuera del entorno demo.
- Bandejas y avisos persistentes; no dependen de memoria del navegador.
- Migraciones aditivas y configuración Coolify; salud de DB/storage/Redis; respaldo coordinado y restauración en esquema/bucket aislados.
- Workflow .github/workflows/ci.yml valida el perfil exacto de Coolify: arranque automático desde cero, API/motor/browser, código privado y persistencia tras redesplegar. La instalación pública de evaluación requiere un código de invitación antes de acceder a las cuentas sintéticas.

## Trabajo dependiente del ambiente institucional

| Dependencia | Información/acceso necesario | Criterio para habilitar |
|---|---|---|
| Identidad/firma estatal | Emisor/cliente/callback/JWKS, certificados y políticas | Pruebas contra sandbox institucional; desactivar proveedor y cuentas dummy |
| eBROU | Convenio, contrato de API, credenciales, ambiente de prueba y conciliación | Transferencia/errores/webhooks/conciliación e idempotencia homologados; sustituir puerto de simulación |
| Expediente oficial | API, credenciales y reglas de actuaciones | IDs oficiales y documentos reconciliados con el gestor institucional |
| Infraestructura | Host/domino/Coolify, TLS, red ANTEL/REDuy, almacenamiento y secretos | Despliegue privado, prueba de carga y recuperación en el host real |
| Operación | Destino cifrado externo, frecuencia/RPO/RTO, alertas y responsable | Backups programados por el operador del host, restauración periódica y alertas readiness probadas |
| Notificación externa | SMTP/canal institucional y preferencias de destinatarios | Entrega/reintento/privacidad verificadas; hoy opera la bandeja interna |
| Datos maestros | Unidades, responsables, catálogo, tasas/ICC y fuentes vigentes | Aprobación de datos reales; no sustituir con valores demo |
| Retención | Plazos y clasificación acordados con Jurídica/Archivo | Política S3/DB/backup formal; no habilitar borrado automático ni WORM irreversible sin esa política |

No se configuraron servicios externos, envíos a terceros, pagos reales, homologaciones ni políticas institucionales no suministradas. No se recomienda habilitar dinero real manteniendo el simulador o el proveedor dummy.

## Antes de la presentación

Para una evaluación remota seguir DEPLOYMENT_COOLIFY.md, comprobar el dominio HTTPS y `/api/health/ready`, y entregar privadamente el código de invitación. Para la instalación local mantener Docker Desktop abierto y consultar DEMO_GUIDE.md. El escenario Transferencia electrónica Demo queda sin pagar para la primera prueba del presentador. El seed es idempotente y no reinicia procesos usados. No ejecutar down -v ni reset sobre datos que deban conservarse.
