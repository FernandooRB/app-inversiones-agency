# Contraste USD/MXN

La app permite subir una referencia CSV para activos en USD y moneda base MXN.
No reemplaza la fuente del análisis principal ni su PDF.

## Formato
Columnas exactas Date,USDMXN, separadas por comas. Fecha ISO YYYY-MM-DD,
punto decimal, tasas positivas en pesos por dólar y sin fechas duplicadas.
Límite: 1 MB. El usuario declara fuente/enlace y metodología/hora/zona.
La app no certifica la autenticidad de la referencia ni corrige desfases automáticamente.

Se intersectan las fechas de activos, Yahoo y referencia sin rellenar.
Con menos de 60 precios solo se comparan tasas. A partir de 60, ambas fuentes
se recalculan sobre las mismas fechas: primero con los pesos del análisis principal,
después se reoptimiza máximo Sharpe por fuente. Si hay huecos, los retornos abarcan
varias sesiones: el resultado debe interpretarse con esa limitación de calendario.
Las métricas se muestran como fracciones salvo Sharpe.

## Muestra independiente incluida
fx_reference_fed_sample.csv contiene cinco observaciones transcritas de la fila
MEXICO/PESO de H.10. Es una muestra puntual, no una serie completa.

- 2024-01-02: https://www.federalreserve.gov/releases/h10/20240108/
- 2024-06-03, 04 y 07: https://www.federalreserve.gov/releases/h10/20240610/
- 2024-06-28: https://www.federalreserve.gov/releases/h10/20240701/

Las fechas son las columnas de observación de las tablas, no la fecha de publicación.
No se debe suponer que H.10, FIX y Yahoo comparten horario o metodología.
Para una comparación completa, preparar la serie del periodo con la convención temporal
documentada por su fuente. No desplazar días para mejorar coincidencias.

Las capturas y datos aportados por el usuario permitieron reproducir media 55.1956%,
volatilidad 21.6662%, Sharpe 2.4091, VaR histórico 3.340556% y CVaR 3.847145%,
con 123 retornos, pesos 30/70, tasa 3%, confianza 95% y horizonte 5 sesiones.
Esto acredita consistencia numérica; el contraste externo completo sigue pendiente.
