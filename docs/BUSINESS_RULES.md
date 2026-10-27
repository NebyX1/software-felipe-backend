# Reglas de negocio y decisiones de implementación

## Identidad y alcance

El proveedor demo sólo acepta cuentas activas y marcadas `demo` en MariaDB, con el modo explícitamente habilitado. JWT identifica un ID; cada petición recupera rol, estado y empresa desde DB. Logout revoca el `jti`. Cuenta demo deshabilitada no accede aunque conserve un token. Seleccionar una cuenta es la autenticación ficticia autorizada, no una facultad de modificar roles.

Administrador/Dirección General ven todo; administrativo y consulta tienen lectura global con acciones propias. Director, técnico e inspector requieren asignación o autoría del alta. La nueva intervención asigna automáticamente a su creador. Empresa sólo accede a intervenciones adjudicadas a su compañía activa. Un cambio contractual conserva esa empresa: una contratación independiente de otra compañía requiere intervención/expediente propio; evita compartir historiales privados de adjudicatarias distintas.

Documento público: accesible dentro del recurso autorizado; reservado: empresa de la obra o equipo interno; interno: equipo interno; confidencial: administración/Dirección General. La vista pública utiliza una lista explícita de campos de obras publicadas; no entrega profesionales, representantes, adjuntos o chats. Las URLs temporales duran 60 segundos y revalidan sesión, compañía y recurso al descargar.

## Versiones y estados

`version` en PATCH/transición debe coincidir con la actual. Una discrepancia devuelve 409. Las operaciones críticas bloquean la intervención y, cuando corresponde, certificado/pago con `FOR UPDATE`. MariaDB usa READ COMMITTED: una petición que espera el lock debe leer el certificado ya confirmado por la ganadora. Restricciones únicas por período, clave de idempotencia y versión complementan los locks; conflictos no se transforman en doble registro.

Etapa y estado operativo son independientes. Proyecto → Obra exige empresa habilitada, contrato/rubrado contractual aprobado y cronograma contractual aprobado. Obra → Posobra exige ejecución ponderada completa y plano final. Cambios contractuales crean versiones, conservan rubros ya certificados y requieren motivo; no editan certificados aprobados. Cambios de alcance enlazan valoración, documentación y, si corresponde, cronograma revisado para autorización de Dirección General. Lluvia, paro y feriado son incidencias: sólo una prórroga aprobada modifica el fin.

Tareas: pendiente → en curso → bloqueada/revisión → finalizada; cancelación y retornos según servicio. Responsable o dirección cambia el estado y registra comentario. Observación: observado → respuesta de empresa → revisión/cierre o nueva observación. No se cierra sin respuesta. Visitas e incidencias conservan autor, fecha, descripción y evidencias. Planes/informes editables conservan actuación/versiones; actas y resoluciones cerradas se conservan.

Documento: cargado → validado/observado → validado → archivado. Una nueva versión sustituye el índice vigente de la anterior, preservando bytes y anotaciones originales. Baja es lógica; documentos de certificado/rectificación aprobados y actas de recepción se retienen. MinIO guarda bytes privados, MariaDB metadatos y SHA-256. Tipos/MIME, estructura ZIP, macros, acciones PDF, páginas, dimensiones y límite de 20 MB se validan.

## Economía determinista

La IA no participa en cálculos. Decimal con contexto de 40 dígitos; cantidades, precios y porcentajes/tasas contractuales se persisten hasta 8 decimales; moneda a 2, ROUND_HALF_UP. La precisión declarada del avance almacenado es una fracción con 8 decimales. Las cantidades ejecutadas exactas se conservan además en la instantánea para no perder unidades en fracciones como un tercio.

`total_rubro = redondear(cantidad × precio)`. Cada certificado conserva anterior, período y acumulado. Las cantidades exactas acumuladas forman un libro por rubro. El importe del período es la diferencia entre importes acumulados redondeados; así tres cantidades de 1 sobre un contrato de 3 unidades cierran su saldo monetario exactamente. LLSS utiliza el mismo criterio acumulado. Un acumulado exacto fuera de [0,1] o una diferencia negativa se rechaza antes de redondear.

Modalidades: **período**, porcentaje que se suma al anterior; **acumulado**, porcentaje total y período por diferencia; **cantidad**, unidades del período; **importe**, importe base del período antes de impuestos. Un campo acumulado vacío conserva el anterior. La pantalla borra valores al cambiar modalidad y exige previsualización backend antes de guardar. No mezcla cantidad y porcentaje.

IVA y LLSS pertenecen a la versión de contrato/rubro; fracciones entre 0 y 1. No hay tasa social universal. `social_payment=separado` informa aportes sin sumarlos al pago de empresa; `incluido` sí los suma. Básico, imprevisto y ampliación se desglosan; `contingency_limit` acota la reserva. El avance de cada rubro no supera el contrato y ampliaciones requieren nueva versión autorizada.

ICC: `(índice_actual / índice_inicial − 1) × base_elegible_del_período`, sin IVA; IVA del ajuste por separado. Los índices inicial y actual son parámetros contractuales positivos y versionados, sin consulta automática a una serie externa. Las tasas sociales pertenecen a cada rubro y contrato; no se universalizan.

Avance físico ponderado = base aprobada acumulada / suma cantidad×precio contractual vigente. No es promedio simple de porcentajes. Certificado monetario incluye impuestos/ajustes según reglas; pagado sólo incluye expedientes en `pagado`. Previsto temporal = fracción de tiempo transcurrido entre fechas de ficha; se presenta explícitamente como referencia temporal, no como avance físico ni una curva de producción inventada. El horizonte quinquenal filtra fechas y agrupa presupuestos por año de inicio, sin suponer flujo de caja.

## Certificado, factura y expediente

Una certificación pendiente por obra y un período único, creciente. Reintento con misma clave y contenido devuelve el original; reutilización con contenido distinto, otro período duplicado o concurrencia incompatible devuelve 409. Empresa crea borrador → presenta; Dirección de Obra observa o aprueba inicialmente; empresa subsana con nueva revisión/presentación y, después de aprobación inicial, adjunta factura PDF de su obra/empresa. Dirección General observa o aprueba definitivamente. La observación invalida aprobación inicial y vínculo de factura para una nueva revisión.

La aprobación final vuelve a calcular contra anteriores aprobados y fija instantánea de contrato, rubros, cantidades, precios, tasas, ICC, importes, factura/hash, período, fechas y actores. Genera certificado y nota PDF. Si MinIO falla después de aprobar, `pdf/retry` recupera la generación sin duplicar aprobación ni pago. Los documentos provienen de la instantánea y llevan indicación DEMO.

Rectificación explícita: solicitud con motivo y cálculo completo; Dirección General aprueba/rechaza; se agregan instantáneas antes/después, diferencia, identidad y anexo PDF. El original no se sobrescribe. Se resuelve en el último período, antes del pase a Hacienda y de abrir otro período. Este límite preserva la cadena acumulada y evita corregir un pago ya tramitado sin un circuito financiero de devolución documentado. Una rectificación pendiente bloquea período siguiente y pase administrativo. Una aprobada actualiza el importe del expediente y los indicadores usando su instantánea efectiva; las revisiones originales permanecen.

Expediente interno DEMO → Hacienda (confirma disponibilidad) → Secretaría General → resolución (Dirección General registra el borde Intendente simulado con adjunto) → Contaduría/Tesorería → pagado ficticio (comprobante, comentario y confirmación explícita). No hay transferencias ni firma estatal. La identidad de cada actuación y evidencias quedan auditadas.

## Importación y posobra

XLSX/ODS conservan original y preview con hash, filas, hoja, errores/advertencias. Se interpretan referencias y operaciones aritméticas/SUM en un AST acotado; no eval/macros, ni cachés como autoridad. Un subtotal con detalle no se importa como ítem adicional. Unidades desconocidas, código duplicado, valores inválidos, fuentes externas o fórmulas defectuosas bloquean confirmación. Confirmación y persistencia son transaccionales; propuesta IA de mapeo es sólo asesoría revisable.

Un enlace a un archivo ausente, un nombre roto, una fórmula incorrecta o un acumulado mayor a 100% bloquean la importación. El registro profesional es privado y no se usa en seeds. Cuando falta CI, se conserva vacía y se propone un identificador interno basado en hash/posición, sujeto a confirmación; no se inventa identidad institucional.

Recepción provisoria/definitiva exige acta PDF, fecha real y etapa posobra. Definitiva requiere plazo cumplido, observaciones cerradas, manual y plan ejecutable de mantenimiento. El vencimiento de la provisoria produce alertas; al completar definitiva se marca cumplida. Mantenimiento exige responsable, fecha y periodicidad; realizado requiere informe/evidencia; revisión de Dirección General. Al revisar uno recurrente se genera el hito siguiente (mensual, trimestral/estacional, anual), con referencia al anterior; el plan puede editarse con versión y auditoría. La periodicidad estacional se interpreta trimestral, documentada y editable, sin inventar una estación institucional.

## Pago electrónico simulado, trámites y representación

Transferencias internas: el expediente debe estar en Contaduría/Tesorería; importe y empresa se toman del registro autorizado, con bloqueo de obra/pago. Un único intento pendiente; clave idempotente vinculada a actor/expediente. Rechazar/cancelar conserva el importe impago; aprobar fija referencia, importe, fecha y PDF reservado, incrementa versión y contabiliza pagado. Fallo de storage revierte la decisión DB y permite reintentar. La respuesta final no puede cambiarse. Comprobante y evidencias de trámites se conservan. Sólo funciona con ambos flags de demo habilitados y pago marcado demo.

Trámite documental: solicitante presenta/subsana; revisor inicia revisión y observa/decide. Pase exige unidad y responsable revisor con acceso a la intervención; las decisiones quedan restringidas al responsable asignado o administración/DG. Todas las actuaciones requieren comentario y control de versión. Empresa consulta sus propios trámites, documentos y notificaciones; no se divulgan descripciones de trámites internos en avisos.

Representación: empresa activa, validación explícita y fechas vigentes son condiciones independientes. El perfil privado permite completar documentación aun si falta validación; el acceso a obras queda bloqueado. Nuevos representantes nacen pendientes; validación por admin/DG exige evidencia de representación de su empresa. Sólo seed identificado como demo crea vigencia sintética. Revocar o vencer la representación impide también descargas/contexto con sesión previa.

Los avisos viven en MariaDB y se revalidan por destinatario/alcance. Los compromisos próximos (7 días) generan aviso único por registro/fecha; completar o reprogramar lo retira de la bandeja. Canal implementado: bandeja interna. Envío SMTP institucional requiere configurar el borde externo y no está activo en la demo.

Para Tesorería, una orden ficticia de una obra nueva también requiere autor y empresa sintéticos cuando la obra no forma parte del seed. Esa condición no cambia el marcador de reset. El perfil Empresa sólo opera fixtures explícitos de su propia empresa; una orden ordinaria conserva consulta desde ese perfil.
