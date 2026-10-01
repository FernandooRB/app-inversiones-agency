# Primer piloto con datos reales de clientes

**Objetivo:** producir un análisis y PDF reproducibles a partir de documentos reales, con revisión
humana y evidencia verificable. Los ejemplos ficticios sólo prueban el software. Este plan es una
lista de condiciones para decidir si se puede ejecutar y entregar el piloto; no constituye una
opinión jurídica ni sustituye la revisión de contratos y políticas aplicables.

## Decisión previa: alcance del servicio y actividad externa

El producto deseado analiza el perfil y la cartera de cada cliente para proponer asignaciones. El
[artículo 225 de la Ley del Mercado de Valores](https://www.diputados.gob.mx/LeyesBiblio/pdf/LMV.pdf)
incluye el análisis y las recomendaciones de inversión individualizadas prestados de manera habitual
y profesional en la figura de asesor en inversiones, para la que exige registro ante la CNBV. La
certificación profesional es un requisito distinto del registro; constituir una persona moral o usar
la palabra «consultoría» no cambia por sí solo la actividad realizada. Un abogado especializado debe
revisar el servicio, la página, el contrato y un PDF representativo, y dejar por escrito la ruta
aplicable antes de ofrecer asignaciones individualizadas.

Si quien presta el servicio tiene otro empleo, debe revisar las políticas de actividades externas
y conflictos de interés que le correspondan y obtener las autorizaciones escritas exigibles antes
de ofrecer el servicio. Si la actividad no puede autorizarse, se debe cambiar su alcance o aplazar
la prestación personalizada; una aprobación técnica del software no resuelve ese conflicto.

**Salida de esta decisión:** dictamen de alcance, decisión laboral documentada, tipo de entregable
permitido y texto aprobado para la página y el contrato. Ningún PDF personalizado pasa a entrega
comercial mientras este punto siga pendiente.

## Alcance mínimo del piloto técnico

El primer intermediario será **GBM**. Para el ensayo técnico se dispone de estados de cuenta de
una **cuenta propia** en PDF y XML, con acciones BMV/SIC, FIBRAS y ETF declarados por el usuario.
La [revisión local](gbm_own_account_intake.md) distingue los estados PDF de los XML CFDI y
comprueba aritmética de portada, subtotales visibles, saldos corridos de efectivo, cambios de
cantidades de renta variable y plausibilidad de los días impresos. También compara los netos de
compraventas y reportos visibles con cantidad, precio y cargos impresos, y verifica la
correspondencia estructural entre compras y vencimientos de reporto. Los resultados específicos
y la asociación verificada de las series PDF con sus contratos permanecen en un
informe privado. Aún faltan registros normalizados de posiciones y movimientos, asociación de
todos los CFDI, conciliación completa de cantidades y eventos corporativos, y resolución de
excepciones.
El ensayo usará únicamente instrumentos cuya identidad, precios y uso de
datos puedan comprobarse. Se ampliará a otros intermediarios y tipos de activo después de
cerrar el primer caso sin excepciones materiales. Los documentos reales no se incluirán en commits,
pruebas automáticas, issues, PR ni ejemplos del repositorio público.

El ensayo con cuenta propia puede avanzar en paralelo a las decisiones de servicio, siempre que
los documentos se manejen en un entorno privado y no se generen entregables para terceros. La
información de esa cuenta también es confidencial y no debe enviarse al repositorio.

Para una prueba local, `data/private/`, `output/private/` y `tmp/private/` están excluidos de Git;
la exclusión evita un commit accidental, pero **no cifra ni controla el acceso**. Se debe usar un
equipo y almacenamiento autorizados, con cifrado y acceso restringido, y revisar los archivos
preparados antes de importarlos a la app.

| Frente | Evidencia necesaria fuera del repositorio | Condición para avanzar |
| --- | --- | --- |
| Contratación y privacidad | Contrato y aviso de privacidad revisados; finalidad, responsables, consentimiento cuando corresponda, plazo de conservación y canal de derechos ARCO | Recepción y uso de datos autorizados para el servicio definido |
| Recepción y acceso | Canal cifrado, acceso por rol, OIDC probado en el dominio final, registro de accesos, copia de seguridad y prueba de borrado | Sólo el equipo autorizado puede ver el expediente; recuperación y eliminación probadas |
| GBM | Estado de cuenta, posiciones, efectivo, operaciones, eventos y tarifario aplicable del mismo periodo | Fecha, universo, cantidades y totales conciliados; cada diferencia explicada |
| Datos de mercado | Contratos o permisos por producto, mercado y uso, manifiestos de derechos, identidad de series y dos fuentes autorizadas comparables | Ningún instrumento con licencia, identidad o precio material sin resolver |
| Modelo | Supuestos, parámetros, comparación contra cartera actual y referencia simple, pruebas fuera de muestra y estrés | Resultados reproducibles y limitaciones explícitas; revisión humana independiente |
| Entrega | PDF versionado, fuentes y huellas, aprobaciones de dos revisores, canal autorizado y acuse | Sólo se entrega el contenido permitido por el dictamen y el contrato |

La [Ley Federal de Protección de Datos Personales en Posesión de los Particulares](https://www.diputados.gob.mx/LeyesBiblio/pdf/LFPDPPP.pdf)
exige informar finalidades mediante aviso de privacidad y mantener medidas administrativas,
técnicas y físicas de seguridad. La app actual procesa CSV en sesión, pero no equivale a un sistema
de expedientes con retención, borrado, control de acceso y respuesta a incidentes probados.

### Mapa de extracción del caso GBM

Ya se observó una exportación CSV mensual de movimientos con 13 campos; su
[revisión estructural](gbm_own_account_intake.md#exportación-mensual-de-movimientos-csv) comprueba
el formato y detecta copias idénticas, pero no la integridad ni el vínculo contractual. No se
presume que todos los productos de GBM tengan el mismo diseño ni que una exportación sea una fuente
de precios con derechos comerciales. El titular confirmó que **no puede descargar el historial
de movimientos de su cartera BMV**: ese CSV previo no es requisito del piloto BMV. Se aplicará la
[conciliación desde PDF](gbm_own_account_intake.md#conciliación-cuando-no-hay-descarga-de-movimientos).
La primera revisión usará esta correspondencia:

Los XML reconocidos como CFDI no contienen posiciones estructuradas al corte. Los PDF serán la
fuente de las posiciones y movimientos del piloto; una extracción específica debe contrastarse
visualmente y con subtotales del estado. No se deducirán operaciones ausentes. Los campos exactos
de cada sección se documentarán con ejemplos sintéticos antes de activar un importador.
En una revisión anterior de 11 CFDI del piloto propio, siete tenían total cero por descuento
completo y cuatro importe positivo; su aritmética interna cuadró. Esto no concilió sus cargos con
los estados: uno de los cuatro positivos carecía de referencia contractual explícita y ninguno
coincidió individualmente con una fila de comisión más impuesto del PDF. La revisión ampliada de
2026 identifica 18 CFDI estructurales con aritmética interna exacta entre 22 XML distintos; cuatro
no son CFDI reconocibles por el control actual. No se ha repetido la conciliación de cargos para
todos los comprobantes nuevos. Véase la [revisión GBM](gbm_own_account_intake.md).
La ubicación del archivo no basta para asignarlo a una cuenta; el vínculo, periodo y alcance de
cada cargo requieren una fuente o revisión adicional antes de usarlos en el perfil de costos.

| Documento o dato GBM | Control que lo utilizará | Comprobación independiente |
| --- | --- | --- |
| Posiciones y valor al corte | Cartera actual, detalle y subtotal | Total y fecha del estado original |
| Efectivo y partidas pendientes | Cobertura de cuenta | Total de cuenta del estado original |
| Movimientos de efectivo | Puente de efectivo liquidado | Saldos inicial y final del periodo |
| Cantidades y operaciones de títulos | Puente de cantidades | Posiciones finales transcritas del estado original |
| Comisiones y condiciones del cliente | Perfil de costos por intermediario | Tabla pública y cargos observados; convenio particular si existe o difiere |
| Dividendos, intereses y retenciones | Registro de flujos fiscales | Constancias y movimientos revisados por especialista |
| Identidad y precios de cada serie | Manifiestos y contraste de fuentes | Fuente de mercado autorizada y comparable |

La conciliación automática detecta diferencias aritméticas entre archivos declarados. Una persona
debe comprobar la cobertura de las fuentes disponibles y que correspondan al mismo periodo,
cuenta, instrumento, moneda y convención de liquidación.

## Secuencia de ejecución

1. **Definir el producto permitido.** Obtener el dictamen jurídico y la respuesta laboral. Revisar
   la página, el contrato y las palabras del PDF según esa decisión.
2. **Preparar el entorno de datos reales.** Definir aviso y contrato; configurar recepción segura,
   accesos, almacenamiento, respaldo, plazo y borrado. Probar acceso autorizado y no autorizado.
3. **Preparar el caso GBM.** Escoger universo y fechas; revisar el formato del estado y los
   movimientos disponibles, y obtener licencias de datos. Separar los identificadores de cuenta de
   los archivos que usa el motor.
4. **Conciliar.** Reproducir posiciones, cantidades, efectivo, operaciones, dividendos, comisiones
   y precios desde documentos independientes. Registrar excepciones, responsable y resolución.
5. **Validar el análisis.** Recalcular supuestos, costos y escenarios; comparar con cartera actual y
   referencias simples; verificar sensibilidad del resultado a fechas y datos.
6. **Revisar y decidir.** Dos personas firman la conciliación y el PDF. La entrega requiere que no
   haya diferencias materiales abiertas y que todos los permisos de uso sean vigentes.

Si una fuente no permite el uso comercial o un dato no puede conciliarse, el caso queda detenido o
se reduce el universo con una exclusión documentada. Un resultado matemático o un CI aprobado no
constituyen aprobación del caso real.

## Revisión previa por cuenta y siguiente trabajo

La app reúne en una tabla los controles disponibles para la cuenta: alcance y huellas de archivos,
derechos declarados de precios, identidad de series, cartera y conciliaciones de detalle, subtotal,
cobertura, efectivo y cantidades, reglas de costos, contraste de fuentes y alertas de precios. Cada
fila muestra `EVIDENCIA_CARGADA`, `PENDIENTE` o `ALERTA`. El estado cargado sólo indica que el
archivo fue aceptado o la comprobación automática pasó; no acredita la autenticidad del documento,
la integridad de movimientos, la elegibilidad contractual de la tarifa ni los derechos comerciales.
La revisión de originales, excepciones, impuestos, PDF y firmas, así como el permiso jurídico,
laboral y de privacidad, permanecen pendientes. La aplicación nunca cambia automáticamente un caso
a «apto para cliente» y ambos PDF se identifican como borradores internos.

El siguiente trabajo es **cerrar las excepciones de la cuenta propia y verificar fuentes y permisos
de uso**, guardando actas y documentos sólo en el expediente privado. Después se define el entorno
de recepción, acceso, almacenamiento y borrado para clientes reales. Los requisitos exactos de
almacenamiento y entrega se implementarán después de las decisiones jurídica, laboral y de
privacidad; la app actual no está autorizada para alojar expedientes de clientes.
