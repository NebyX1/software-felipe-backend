# Contratos de API

Base `/api`. JSON con UTF-8. Autorización `Authorization: Bearer <token>`; no enviar rol/empresa como autoridad. Errores `{code,message,fields,request_id}` cuando aplica: 401 sesión, 403 permiso, 404 recurso fuera de alcance, 409 versión/circuito/conflicto, 413 tamaño, 422 validación, 503 servicio. No devuelve stack, claves ni URL de S3.

## Identidad y fichas

| Método / ruta | Entrada / salida | Política |
|---|---|---|
| GET /auth/accounts | cuentas demo activas | sólo modo demo habilitado |
| POST /auth/login | `{account:"tecnico@demo.invalid"}` → token/user/provider | proveedor demo y limitación Redis |
| GET /auth/me; POST /auth/logout | user; revocación | token válido |
| GET /works | works/metrics/total/page/pages | alcance + filtros |
| POST /works | name, description, locality, location, type/objective, coordinates, surface, budget, dates, funding, unit_id | editores; crea asignación propia |
| GET/PATCH /works/:id | ficha/metrics/actors; PATCH `{version,...}` | alcance + edición |
| POST /works/:id/transition | `{version,stage}` o `{version,status,reason}` | dirección y condiciones |
| GET /dashboard; GET /works/map | agregados/alertas; fichas geográficas | filtros idénticos |
| GET /reference | companies, units, users, professionals, catalog | datos mínimos según rol |
| POST/DELETE /works/:id/actors[/:assignment] | user_id XOR professional_id, role, contact | dirección |

Filtros: `q`, `stage`, `status`, `locality`, `objective`, `responsible_id`, `year_from`, `year_to`; listado añade `sort=name|budget|start_date|created_at`, `page`, `per_page` (1–100). Coordenadas y importes son strings decimales. Los campos `funding` contienen `{name,amount}`. Vista pública: GET `/public/works`, `/public/geojson`, únicamente lista blanca y obras publicadas.

## Planificación, documentos e importación

| Ruta | Operaciones |
|---|---|
| /works/:id/contracts | GET con líneas; POST nueva versión con kind/rules/lines y metadatos de adjudicación |
| /works/:id/contracts/:contract/approve | POST dirección; motivo para revisión |
| /works/:id/contracts/:contract/export.pdf o .xlsx o .csv | GET exportación autorizada |
| /works/:id/schedules | GET/POST `{kind,reason,activities:[{title,start,end,responsible_id,code,milestone}]}` |
| /works/:id/schedules/:schedule/approve | POST aprobación de línea base |
| /works/:id/records | GET opcional kind; POST según tipo con title/date/due_date/responsible_id/data |
| /works/:id/records/:record | PATCH planificación/informe con version |
| /works/:id/records/:record/transition | POST `{version,status,comment,document_ids}` |
| /works/:id/documents | GET; POST multipart file/kind/classification/previous_id/record_id |
| /documents/:id/download | GET attachment; `inline=1` preview, integridad verificada |
| /documents/:id/link | POST → URL firmada y expires_in=60 |
| /document-link/:signed | GET revalida permiso/sesión/empresa |
| /documents/:id | DELETE baja lógica con retención protegida |
| /documents/:id/transition | POST `{status,comment}` revisión documental |
| /documents/:id/annotations | GET/POST `{page,x,y,text}`, posiciones normalizadas [0,1] |
| /works/:id/imports/preview | POST multipart file/kind/sheet/advance_column → import.preview y SHA |
| /imports/:id/confirm | POST `{confirm:true,sha256,contract}` según tipo; devuelve rubrado/profesionales/avances |

Rubros `{code,chapter,description,unit,quantity,unit_price,social_rate,kind,icc_eligible}`. Reglas `{iva_rate,social_payment,icc_initial?,contingency_limit?}`. Unidades conocidas m2/m3/ml/un/global/kg/h/l/t; sólo equivalencias verificadas. Avances importados se pasan al formulario, no aprueban certificados automáticamente.

## Certificación y pagos

Ejemplo de creación por empresa:

```json
{"period":"2026-10","mode":"periodo","advances":{"1.1":"25"},"icc_current":"115.52","idempotency_key":"una-clave-unica-de-al-menos-16-caracteres"}
```

- GET/POST `/works/:id/certificates`; POST `/works/:id/certificates/preview` devuelve calculation sin persistir.
- PATCH `/works/:id/certificates/:cert` `{version,mode,advances,icc_current}` sólo borrador/observado; GET `/revisions` conserva cada entrada.
- POST `/transition` `{version,status,comment?,invoice_id?,invoice_number?}` según rol/circuito.
- POST `/pdf/retry` recupera PDFs pendientes después de aprobación final.
- GET/POST `/rectifications`; solicitud `{reason,mode,advances,icc_current}`. POST `/rectifications/:correction/resolve` `{version,status:"aprobada"|"rechazada"}`.
- GET `/works/:id/payments`; POST `/payments/:payment/transition` `{version,status,comment,document_ids,budget_available?,confirm_demo?}`.
- GET `/works/:id/history`, `/works/:id/dossier.zip`, `/reports/works.pdf|xlsx|csv` con filtros.

Respuestas incluyen `certificate`, `payment` o `rectification` con versión actual. Calculation expone base, IVA, LLSS, ajuste/IVA ajuste, payable, reglas y rubros anteriores/período/acumulados. Original aprobado conserva approved_snapshot.

## Administración e IA

GET/POST `/admin/companies|professionals|users|units|catalog`, PATCH `/:id`. Sólo administrador. Nuevas cuentas demo requieren `demo:true` y entorno demo; no se puede elevar el rol por editar desde navegador. GET `/admin/audit/events` para administrador/DG. `/admin/` es el panel Flask con sesión y CSRF, separado del JWT de API.

POST `/documents/:id/ingest`, DELETE `/documents/:id/index`. GET `/works/:id/search?q=...` retorna fragmentos autorizados. GET `/works/:id/chat` historial privado del usuario; POST `{query}` devuelve SSE `context`, `token`, `done` o `error`, con keepalive. `context` sólo metadata de fuentes autorizadas; `done.turn.sources` contiene citas válidas. El cliente descarta texto provisional ante error y nunca lo registra como respuesta completa. POST `/ai/import-mapping` `{headers:[...]}` retorna propuesta estructurada con revisión humana obligatoria.

GET `/health` y `/api/health/live` salud del proceso; `/api/health/ready` verifica MariaDB/Redis/MinIO. Ollama no integra readiness general. Descargas y SSE funcionan a través de Nginx; una ruta API inexistente devuelve JSON 404 y nunca el HTML SPA.

## Ampliación: simulador, bandeja y empresas

- GET `/payments`: expedientes sólo de intervenciones visibles, obra/período/estado/importe.
- GET/POST `/works/:work/payments/:payment/attempts`: POST `{version,idempotency_key,confirm_demo:true}` registra pendiente. Importe/destinatario se resuelven en servidor. Repetir la misma clave/actor/expediente devuelve el mismo intento; otra operación pendiente bloquea duplicados.
- POST `/works/:work/payments/:payment/attempts/:attempt/resolve`: `{status:aprobada|rechazada|cancelada,reason}`. Aprobar genera documento privado y marca pagado en la misma transacción. Respuesta repetida idéntica es idempotente; contradictoria da 409. Rechazo conserva expediente en Tesorería. Sólo administrativo/DG/admin, exclusivamente entorno demo.
- GET `/inbox`: trámites, certificados pendientes y compromisos autorizados. GET `/notifications`; POST `/notifications/:id/read`: avisos persistentes del destinatario, alcance revalidado y vencimientos idempotentes.
- GET/POST `/works/:work/procedures`: alta `{title,description,due_date?,document_ids}`. POST `/:procedure/transition` `{version,status,comment,document_ids?,unit_id?,responsible_id?,due_date?}`. Estados borrador→ingresado→en_revision→observado→subsanado→ingresado; revisión→aprobado/rechazado→archivado. `status:derivar` preserva estado y registra unidad/responsable/plazo; exige revisor con acceso a la obra. Evidencias quedan protegidas contra eliminación.
- GET `/company/profile` o GET/PATCH `/companies/:id/profile`: empresa propia o administrativo/DG/admin. PATCH sólo `{contact:{email,phone,address,contact_name}}`.
- POST `/companies/:id/documents`: multipart `file,kind,previous_id?`; tipos registro/representacion/bps/dgi/otro, almacenamiento privado versionado. GET `/companies/:id/documents/:document/download` verifica hash y alcance.
- POST `/companies/:id/representatives/:user`: admin/DG, `{status:pendiente|validada|revocada,start_date,end_date?,evidence_id?}`. Validación exige documento privado de representación. Obras/descargas/contexto exigen empresa activa y representación vigente; perfil sigue disponible para completar documentación.
- GET `/catalog/historic-prices`: precios desde rubrados aprobados autorizados, fuente/fecha/unidad/contexto.
- GET `/demo/scenarios`: accesos a escenarios sintéticos existentes en DB; vacío fuera de demo.

Nueva migración `7c30aef721f5` añade cinco tablas sin modificar datos existentes. Las representaciones del seed son sintéticas; los nuevos usuarios empresa se crean pendientes de validación.

## Pasarela alojada DemoPay

- GET `/payment-orders`: órdenes autorizadas, estado ready/processing/paid/in_review, comprobante y sesión activa.
- POST `/payment-orders/example`: `{idempotency_key}` carga una orden ficticia lista de $305.000 UYU y antecedentes sintéticos; 201 nueva/200 repetida. No ejecuta aprobaciones bajo identidades ajenas.
- POST `/works/:work/payments/:payment/checkout`: crea o retoma la sesión activa del operador; devuelve `{session}` con `checkout_url`. Sólo órdenes demo en Tesorería. Otra cuenta procesando la orden devuelve 409.
- GET `/checkout/:uuid`: consulta estado persistente. Al consultar una operación cuyo procesamiento ya terminó, el adaptador simulado resuelve y guarda automáticamente la respuesta del banco.
- POST `/checkout/:uuid/authorize`: `{account:operativa|sin_saldo,code:123456}`. Importe y destinatario se toman de la orden guardada; el cliente no decide resultado ni saldo. Respuesta inicial processing, luego succeeded/failed. Operación idempotente por sesión.
- POST `/checkout/:uuid/cancel`: cancela sólo antes de autorizar. Processing requiere esperar el resultado.

Cuenta operativa: $1.500.000 virtuales por sesión; cuenta sin saldo: $0. Tras 2 segundos el servidor compara saldo con importe y crea un comprobante sólo si tuvo éxito. Saldo insuficiente conserva el pago sin pagar y permite una nueva sesión. Sesiones creadas vencen a los 15 minutos. Código incorrecto devuelve 422; orden modificada/operación cerrada devuelve 409.

Alcance y roles se verifican en servidor. Siete perfiles internos demo pueden pagar. Empresa también puede presentar el sandbox en ejemplos propios precargados: identidad y empresa sintéticas, representación vigente, obra/pago demo, código `DEMO-CHECKOUT-…` y snapshot `fixture:true`. Los pagos ordinarios conservan consulta desde Empresa, y Consulta no ordena pagos. Ambas flags demo y usuario sintético son obligatorios. La creación del ejemplo toma la empresa del usuario autenticado y omite cualquier `company_id` enviado por el cliente. Se conserva al usuario Empresa como operador en el historial; no se cambia su rol ni se usan permisos de una cuenta interna.

`/payment-orders` incluye `view:supplier|operator|read_only`; cada orden informa `presentation_mode` y `unavailable_reason`. Los ejemplos propios muestran **Pagar en demo**, y Empresa puede usar **Nuevo pago de prueba** para repetirlos. Una sesión activa de otro operador impide tomar esa orden y muestra una razón explícita. Las operaciones de DemoPay no se pueden resolver mediante el endpoint manual heredado `/attempts/:id/resolve` (409). El importe confirmado, el intento y el PDF se registran bajo bloqueo SQL; el doble envío y la consulta concurrente emiten un solo pago/comprobante. Migración aditiva `c18a903be442`, sin borrar datos.

Patrón de referencia: checkout independiente y retorno de [Mercado Pago](https://www.mercadopago.com.uy/developers/en/reference/online-payments/checkout-pro-orders/overview), e instrumentos ficticios con resultados automáticos de [Stripe](https://docs.stripe.com/testing). DemoPay es un adaptador local de prueba, sin integración con esos proveedores ni banca real.

### Pestañas anteriores a la actualización

Las rutas retiradas `/demo/payment-runs`, `/demo/payment-runs/:id` y `/demo/payment-runs/:id/advance` responden HTTP 410 con `code:client_outdated`, un mensaje en español para recargar y `reload_url:/pagos`. Mantienen autenticación y no leen ni modifican el recorrido anterior. La nueva interfaz detecta cambios de los archivos de entrada al recuperar el foco y cada minuto mientras está visible; pide actualizar después de guardar los cambios. El parámetro anterior `?demo=…` se retira de la URL al abrir Pagos.

## Evaluación privada para Dirección

GET `/auth/accounts` incluye `access_required`. Cuando se configura `DEMO_ACCESS_CODE`, POST `/auth/login` requiere `{account,access_code}`; un código ausente o incorrecto devuelve 403 `demo_access_denied` sin crear sesión. Un cuerpo inválido devuelve 422. El código no se devuelve al cliente, no forma parte del bundle y no reemplaza la identidad/rol que se resuelve en DB.

GET `/demo/scenarios` añade `assistant_available`: informa configuración local, no una promesa de disponibilidad del proveedor. La guía usa sólo las obras autorizadas y no expone claves. GET `/demo/materials/rubrado.xlsx` y `/demo/materials/factura.pdf` requieren autenticación demo y generan archivos sintéticos de práctica sin guardar ni publicar fuentes originales.

La migración aditiva `d42f81b670ce` añade un marcador interno de instalación. `bootstrap.py` serializa migración e inicialización con un lock de MariaDB. Una instalación nueva carga ejemplos una sola vez; una existente sólo migra. La operación interrumpida queda identificada para reintento. Ni el marcador ni el bootstrap cambian roles o reinician pagos y documentos usados.
