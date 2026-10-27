# Integraciones y límites del borde externo

| Borde | Implementación / evidencia | Configuración pendiente |
|---|---|---|
| Identidad institucional | `DemoIdentityProvider` aislado; nueve roles con JWT y RBAC real. Excepción autorizada por el usuario | TuID/ID Uruguay/SSO: emisor, cliente, claves/JWKS, callback y acuerdo; reemplazar proveedor conservando IDs/asignaciones |
| Firma | `SignaturePort` / `DemoInstitutionalAdapter.acknowledge`; actuación interna auditada con ID demo | proveedor/certificado/política de firma estatal; no se presenta una firma electrónica real |
| Expediente | `DossierPort.register`: referencia DEMO, documentos/ZIP y pases internos reales | API/credenciales/ambiente del gestor institucional; no se afirma generación oficial |
| Intendente / resolución | DG registra borde resolución con adjunto y actor interno; señalización demo | identidad y firma institucional de autoridad; no se atribuyen aprobaciones a una persona real |
| Hacienda / Secretaría / Contaduría | estados, disponibilidad, responsables y adjuntos persistentes | conectores institucionales, si se acuerdan; circuito interno funciona sin ellos |
| Tesorería / eBROU | `payment_simulator.py`: intentos persistentes con referencia SIM, pendiente/aprobada/rechazada/cancelada, reintento idempotente y comprobante PDF privado. Deshabilitado fuera de DEMO_ENVIRONMENT + DEMO_AUTH_ENABLED | convenio, credenciales y ambiente oficial de banco; el simulador interno no llama eBROU ni transfiere fondos |
| Ollama cloud | cliente PydanticAI/OpenAI/httpx2 de referencia, API autenticada; streaming real y citas; prueba real separada de mocks | llave/modelo autorizado de la cuenta; secretos privados |
| MinIO / MariaDB / Redis | servicios reales ejecutados, buckets privados/versionados, DB metadata/Decimal y revocación/limitación | credenciales/volúmenes/retención del despliegue |
| OSM / Leaflet | mapa real con datos de API, atribución y selección, UI escritorio/móvil | disponibilidad del proveedor de tiles y política para despliegue institucional |
| IDE / MTOP | adaptador WMS configurable en catálogo; GetCapabilities y GetMap comprobados según evidencia local | seleccionar las capas aprobadas y conservar atribución/condiciones |
| NAS/ANTEL/REDuy/WAF/HIDS/mirror | guía de infraestructura y aplicación compatible | host, contratos, red y accesos operativos no suministrados |

`app/infrastructure/institutional.py` declara puertos separados del dominio. Cada aprobación/pase guarda actor, fecha, recurso, estado y evidencia en MariaDB. Un ID DEMO permanece identificable; las aprobaciones no se atribuyen a organismos externos ni mueven fondos.

La implementación de referencia de IA no tenía Qdrant, FastEmbed, embeddings, reranker ni jobs/streaming. No se eliminó una pila vectorial existente. La extensión implementa ingestión/chunking/versiones en MariaDB, búsqueda textual ponderada y filtros SQL antes de cualquier contenido/cita. Chat usa el proveedor real en streaming y valida citas finales; mapeos usan esquemas Pydantic estructurados. PDFs digitales/TXT/planillas sin errores se indexan; scans/imágenes sin transcripción producen fallo explícito recuperable y no lectura simulada.

Consulta real verificada: `deepseek-v4.1-flash:cloud` en https://ollama.com/v1. Ejecución directa: **3 eventos token**, primera respuesta **6.578 s**, total **6.875 s**, **1 cita autorizada**. Última ejecución a través de Nginx: **1 evento token**, primero **2.672 s**, total **2.75 s**, una cita y propuesta estructurada real válida con confirmación obligatoria. Mocks de pruebas se identifican expresamente y no cuentan como validación del proveedor. La demo local lee la llave existente mediante archivo sólo lectura; no la copia a backend ni frontend.

Servicios geográficos consultados en fuentes oficiales: [Geoservicios IDE](https://www.gub.uy/infraestructura-datos-espaciales/politicas-y-gestion/geoservicios-ide), [Geoportal MTOP](https://geoportal.mtop.gub.uy/geoservicios). Script `scripts/verify_geography.py` registra la evidencia en `tmp/geography-verification.json`. Catálogo `capa_geografica`, por ejemplo `{type:"wms",url:"https://geoservicios.mtop.gub.uy/geoserver/ows",layers:"geoportal_capas_base:localidades_ptos_pg",attribution:"MTOP Uruguay"}`. Capas opcionales seleccionables en el control Leaflet; su fallo no bloquea OSM ni las fichas.

Para integrar un borde real: implementar su puerto con timeout/idempotencia, credenciales privadas y IDs externos; conservar actuaciones internas, validar el contrato contra ambiente de testing, agregar pruebas de fallo/reintento y ajustar indicadores de origen `demo/official`. Ninguna integración de identidad o firma institucional se implementó como bypass.
