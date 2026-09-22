# Ruta de validación para un piloto con datos reales

**Destino del producto:** análisis de carteras y documentos basados en datos reales de clientes, no en
casos inventados. Los casos ficticios del repositorio sirven sólo para pruebas y revisión visual.
La aplicación actual importa datos de posiciones sin identificadores y no conserva expedientes. Esta
ruta no habilita por sí misma una entrega comercial ni una recomendación individualizada.

## Matriz de aprobación del piloto

Cada fila necesita responsable, fecha, evidencia fuera del repositorio público, decisión escrita y
revisión humana. `Pendiente` significa que no se ha demostrado el criterio; pasar una prueba de código
no equivale a aprobarlo.

| Control | Criterio para aprobar | Estado actual |
| --- | --- | --- |
| Alcance legal y laboral | Revisión jurídica de contratos, reportes y recomendaciones previstas; definición de requisitos CNBV y respuesta del empleador sobre la actividad externa | Pendiente |
| Privacidad y recepción | Finalidad y aviso de privacidad; acceso mínimo, canal cifrado, retención, borrado y respuesta a incidentes probados | Pendiente |
| Derechos de mercado | Contrato vigente por producto, mercado y uso; permiso expreso para cálculo y entregables derivados, con revisión humana del manifiesto | Pendiente |
| Identidad del instrumento | [Manifiesto](instrument_identity.md) de clave/ISIN, mercado BMV/BIVA o SIC, serie exacta, moneda y subunidad, horario, calendario, ajustes y eventos corporativos contrastados | Herramienta formal disponible; contraste externo pendiente |
| Precios independientes | Comparación entre dos fuentes autorizadas en fechas y unidades equivalentes; documentar cada discrepancia material y los huecos | Herramienta disponible; evidencia real pendiente |
| Deuda y fondos | CETES, Bonos M, liquidez y fondos conciliados por emisión/serie con precios, devengado, cupones, distribuciones y estados independientes | Pendiente |
| Posiciones y operaciones | Total, fecha, universo, valuación, efectivo y movimientos conciliados contra estado del intermediario; sin datos personales en repositorio | Pendiente |
| Tarifas e impuestos | Tarifario contractual y constancias fiscales del ejercicio revisados por especialistas; diferencias documentadas por régimen e instrumento | Pendiente |
| Modelos y reportes | Comparativos fuera de muestra en varios regímenes y universos, revisión de supuestos, PDF legible y doble firma humana antes de entrega | Pendiente |
| Acceso operativo | Login OIDC, rechazo de usuario no autorizado, expiración y cierre de sesión probados en el dominio definitivo | Pendiente |

## Procedimiento de conciliación de precios

El módulo `price_source_validation.py` acepta dos CSV de precios ajustados y dos manifiestos de derechos
confirmados, con el mismo universo y periodo. Exige proveedores distintos y al menos 60 fechas comunes.
Para cada instrumento muestra la diferencia relativa mediana y máxima, las fechas que exceden el
umbral **declarado por el equipo**, y la cobertura entre calendarios. Señala diferencias en el mercado
o la convención de corte de los manifiestos. La app permite descargar sólo fechas, símbolos y diferencias
relativas, sin precios crudos. Las huellas SHA-256 identifican los cuatro archivos de entrada.

`SIN_ALERTAS_AUTOMATICAS` significa únicamente que esos controles no encontraron discrepancias con los
umbrales escogidos. No certifica que ambos proveedores sean correctos, que las cotizaciones representen
el mismo valor negociable, que la moneda declarada sea correcta, ni que el contrato permita entregar
resultados a clientes. Si un instrumento es SIC, una cotización del mercado de origen convertida a MXN
no debe conciliarse como si fuera su cierre local en el SIC.

Para cada diferencia se debe abrir una revisión de evento corporativo, distribuciones, horario,
festivos, tipo de precio, valor de acción, cambio de serie o error de captura. La persona revisora
decide si corrige el archivo de origen, excluye la serie o documenta una excepción. Nunca se reemplaza
silenciosamente un precio con el de la referencia.

## Secuencia para el primer caso real

1. Resolver alcance del servicio y condiciones de empleo; definir tratamiento de datos personales.
2. Conseguir dos fuentes autorizadas y sus contratos; completar metadatos por instrumento.
3. Ejecutar conciliación de precios y de posiciones contra documentos independientes; cerrar alertas.
4. Reproducir costos e impuestos con tarifarios y constancias del caso, revisados por especialistas.
5. Generar el PDF, revisar cifras y fuentes por una segunda persona, versionar la entrega por un canal
   autorizado y aplicar el plazo de conservación acordado.

No se cargarán archivos reales de clientes en pruebas automatizadas, commits, issues o PR públicos.
