# Cotejo independiente en Operación

El punto 29 agrega una comparación de observaciones, con descarga reproducible,
en Operación → Fuentes y alertas. El usuario aporta los dos CSV autorizados.
El objetivo del panel es saber qué falta y qué diferencia revisar por serie y fecha.
Se preservan los controles y la tipografía de SIG. La tabla y la ficha por fila
presentan el mismo resultado, con controles nativos para móvil y teclado.

El lector estructural del importador CSV limita bytes, filas y celdas. Cada fila
declara instrumento o serie, mercado, moneda, unidad, método, hora con zona, fuente,
origen del dato y evidencia. Los plazos y la base de días corresponden a tasas.
Dos distribuidores de una misma fuente original no aportan evidencia independiente.
Se cruzan fechas exactas. Diferencias de identidad o metodología producen pendientes.
La tolerancia es explícita en puntos base y se aplica antes del redondeo visual.

- Probar motor con cálculos independientes, centavos y umbrales exactos.
- Probar diferencias de divisa, hora, ajuste, plazo, origen compartido y archivos inválidos.
- Conectar panel de revisión, práctica ficticia y reporte JSON reproducible.
- Verificar acceso, rendimiento, continuidad, archivos anteriores y publicación.

El panel genera evidencia de comparación para uso interno. Para retomar una
comparación se conservan los dos CSV y sus tolerancias. Los libros, PDF y ZIP
vigentes conservan su estructura. Los datos reales se cotejan localmente.

Fuentes metodológicas: [FIX de Banxico](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadroAnalitico&idCuadro=CF102&locale=es),
[H.10 de la Reserva Federal](https://www.federalreserve.gov/releases/h10/hist/),
[Subastas y colocación de Banxico](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF107&locale=es&sector=7)
y [glosario de la BMV](https://www.bmv.com.mx/es/Grupo_BMV/Glosario).
