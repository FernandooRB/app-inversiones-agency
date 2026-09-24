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
La [revisión estructural local](gbm_own_account_intake.md) distingue los estados PDF de los XML
CFDI. Los resultados específicos y la asociación verificada de las series PDF con sus contratos
permanecen en un informe privado. Falta cerrar la asociación de todos los CFDI, extraer posiciones
y movimientos y conciliar sus importes desglosados.
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

El nombre exacto de cada campo del exportador se confirmará al revisar sus encabezados; no se
presume que GBM entregue todos los campos ni que una exportación sea una fuente de precios con
derechos comerciales. La primera revisión usará esta correspondencia:

Los XML recibidos son CFDI y no contienen posiciones estructuradas al corte. Los PDF serán la
fuente de las posiciones y movimientos del piloto; una extracción específica debe contrastarse
visualmente y con subtotales del estado. No se deducirán operaciones ausentes. Los campos exactos
de cada sección se documentarán con ejemplos sintéticos antes de activar un importador.

| Documento o dato GBM | Control que lo utilizará | Comprobación independiente |
| --- | --- | --- |
| Posiciones y valor al corte | Cartera actual, detalle y subtotal | Total y fecha del estado original |
| Efectivo y partidas pendientes | Cobertura de cuenta | Total de cuenta del estado original |
| Movimientos de efectivo | Puente de efectivo liquidado | Saldos inicial y final del periodo |
| Cantidades y operaciones de títulos | Puente de cantidades | Posiciones finales transcritas del estado original |
| Comisiones y condiciones del contrato | Perfil de costos por intermediario | Tarifario contractual vigente |
| Dividendos, intereses y retenciones | Registro de flujos fiscales | Constancias y movimientos revisados por especialista |
| Identidad y precios de cada serie | Manifiestos y contraste de fuentes | Fuente de mercado autorizada y comparable |

La conciliación automática detecta diferencias aritméticas entre archivos declarados. Una persona
debe comprobar que las exportaciones estén completas y correspondan al mismo periodo, cuenta,
instrumento, moneda y convención de liquidación.

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

## Siguiente trabajo del software

El siguiente cambio técnico debe ser una **revisión previa del caso** que reúna en un solo estado
las evidencias ya calculadas por la app: identidad y derechos de datos, conciliación de cartera,
efectivo y cantidades, fuente de costos, alertas de precios y pendientes de revisión. Debe marcar
claramente qué control falta y evitar que un informe destinado a cliente se confunda con los PDF
internos actuales. Los requisitos exactos de almacenamiento y entrega se implementarán después
de las decisiones jurídica, laboral y de privacidad; no se presupone que la app actual ya está
autorizada para alojar expedientes.
