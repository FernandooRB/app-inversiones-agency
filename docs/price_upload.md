# Importación manual de precios ajustados

La aplicación permite usar un CSV aportado por el equipo como fuente de precios de los
activos solicitados. Esta ruta evita depender de una descarga bursátil de Yahoo para
esos precios; si alguna serie se cotiza en otra moneda, el FX histórico todavía se
consulta mediante la ruta actual de Yahoo. CETES conserva su adaptador separado.

El archivo debe estar en UTF-8 y contener `Fecha` en formato `YYYY-MM-DD` más una
columna por ticker, con los símbolos declarados en la barra lateral. Se admiten
columnas en otro orden; el motor las reordena para coincidir con los tickers. Las
fechas deben ser únicas y crecientes, y cada precio debe ser positivo y finito.
No se rellenan, descartan ni interpolan celdas ausentes. El archivo puede contener
fechas fuera del periodo seleccionado; se analizan sólo las incluidas en él y se
requieren al menos 60 precios comunes en ese tramo. Se rechazan series cuya
separación mediana entre fechas supera un día natural o con un salto interno
superior a siete días naturales, para evitar tratar cierres semanales como diarios.
Ese control no demuestra que estén presentes todas las sesiones de cada mercado.
El límite es 5 MB.

Cada archivo requiere un [manifiesto de derechos](data_sources.md) de una fila con fuente,
producto, mercados, fecha de revisión, vigencia, estado, alcance autorizado, convención de
ajustes, hora de corte/zona y referencia contractual. Sólo se acepta `EstadoDerechos=CONFIRMADO`
y `AjusteCorporativo=AJUSTADO`. La vigencia no puede estar vencida. Los alcances admitidos son
`INVESTIGACION_INTERNA`, `ENTREGABLES_DERIVADOS` y `REDISTRIBUCION_DATOS`; la app advierte cuando
el manifiesto sólo permite investigación interna.

La app incorpora al PDF las huellas SHA-256 abreviadas de los precios y del manifiesto. No guarda
ninguno de los dos CSV en una base de datos; las cargas existen durante la sesión de Streamlit. El
archivo debe contener **precios**, no estados de cuenta, posiciones identificables ni datos
personales de clientes.

La validación informática comprueba estructura, fechas, magnitudes y consistencia formal del
manifiesto, pero no puede
demostrar que un precio sea de cierre, que incluya eventos corporativos y distribuciones,
que tenga la moneda o subunidad esperada, que represente el mercado de negociación
indicado ni que la declaración reproduzca correctamente el contrato. Esas verificaciones
requieren la fuente y su licencia. Para SIC, una serie del mercado de origen convertida
a MXN sigue siendo un proxy económico y no el precio local ejecutable.

Para la [validación del piloto real](real_data_pilot.md) se puede añadir un segundo CSV de precios y
su manifiesto, procedentes de otro proveedor. El contraste interno informa cobertura y discrepancias
por instrumento; no sustituye la revisión de unidad, horario, contrato y eventos corporativos.
