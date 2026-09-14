# Contraste USD/MXN

La app permite subir una referencia CSV o usar la serie H.10 incluida para activos
en USD y moneda base MXN.
No reemplaza la fuente del análisis principal ni su PDF.

## Formato
Columnas exactas Date,USDMXN, separadas por comas. Fecha ISO YYYY-MM-DD,
punto decimal, tasas positivas en pesos por dólar y sin fechas duplicadas.
Límite de carga: 1 MB. Para archivos propios, el usuario declara fuente/enlace y
metodología/hora/zona; la serie H.10 incluida ya documenta estos datos.
La app no certifica la autenticidad de la referencia ni corrige desfases automáticamente.

Se intersectan las fechas de activos, Yahoo y referencia sin rellenar.
Con menos de 60 precios solo se comparan tasas. A partir de 60, ambas fuentes
se recalculan sobre las mismas fechas: primero con los pesos del análisis principal,
después se reoptimiza máximo Sharpe por fuente. Si la intersección omite fechas de
precios dentro del periodo efectivo, solo se comparan tasas: no se calculan métricas
de retornos o riesgo que tratarían intervalos de varias sesiones como días únicos.
Las métricas se muestran en porcentaje y su cambio en puntos porcentuales;
Sharpe y su cambio son adimensionales.

## Referencia H.10 completa para enero-junio de 2024

`fx_reference_fed_h10_2024h1.csv` contiene las 125 observaciones disponibles
del 2 de enero al 28 de junio de 2024 del histórico MEXICO/PESO de la Junta de
Gobernadores de la Reserva Federal de EE. UU. Las columnas Date y USDMXN indican
fecha de observación y pesos mexicanos por dólar estadounidense. Se omitieron
cuatro filas marcadas `ND` por la fuente: 15 de enero, 19 de febrero, 27 de mayo
y 19 de junio. No se interpolaron valores.

Fuente de las observaciones: [H.10, histórico del peso mexicano](https://www.federalreserve.gov/releases/h10/Hist/dat00_mx.htm).
Según la [descripción metodológica H.10](https://www.federalreserve.gov/releases/h10/about.htm),
son tasas de compra alrededor del mediodía en Nueva York para transferencias
pagaderas en moneda extranjera. El histórico se actualiza semanalmente y puede
contener revisiones; la fecha de observación no es la fecha de publicación.
El CSV se transcribió del histórico consultado el 14 de septiembre de 2026.

Esta es una **referencia independiente para sensibilidad**, no una tasa de cierre
de AAPL/MSFT ni una prueba de que Yahoo sea erróneo. No se desplazan fechas para
forzar coincidencias. El usuario puede cargar el archivo con fuente:
`Reserva Federal, H.10, https://www.federalreserve.gov/releases/h10/Hist/dat00_mx.htm`
y método: `Tasa de compra de mediodía, Nueva York (ET), fecha de observación`.
La comparación principal y su PDF siguen usando Yahoo hasta que una convención
alternativa y los derechos de uso se aprueben expresamente.

## Muestra independiente incluida
fx_reference_fed_sample.csv contiene cinco observaciones transcritas de la fila
MEXICO/PESO de H.10. Es una muestra puntual, no una serie completa.

- 2024-01-02: https://www.federalreserve.gov/releases/h10/20240108/
- 2024-06-03, 04 y 07: https://www.federalreserve.gov/releases/h10/20240610/
- 2024-06-28: https://www.federalreserve.gov/releases/h10/20240701/

Las fechas son las columnas de observación de las tablas, no la fecha de publicación.
No se debe suponer que H.10, FIX y Yahoo comparten horario o metodología.
Para otros periodos, preparar la serie completa con su propia convención temporal
documentada. No desplazar días para mejorar coincidencias.

Las capturas y datos aportados por el usuario permitieron reproducir media 55.1956%,
volatilidad 21.6662%, Sharpe 2.4091, VaR histórico 3.340556% y CVaR 3.847145%,
con 123 retornos, pesos 30/70, tasa 3%, confianza 95% y horizonte 5 sesiones.
Esto acredita consistencia numérica. La sensibilidad con H.10 completa y precios
comparables está documentada en `fx_reference_validation_2024h1.md`; sigue
pendiente definir una convención temporal comparable con los cierres de acciones.
