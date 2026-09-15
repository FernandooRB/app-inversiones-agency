# Validación fuera de muestra y revisiones sucesivas

La aplicación separa los retornos cronológicamente en dos ventanas sin superposición. La primera
estima medias, covarianza y pesos de máximo Sharpe y mínima volatilidad. La segunda evalúa esos pesos
sin reoptimizar, junto con pesos iguales y la cartera actual opcional. Exige al menos 60 retornos para
estimación y 20 para evaluación. El usuario elige entre 50 % y 90 % de la muestra para estimar.

La evaluación supone comprar al inicio y mantener los activos sin rebalanceo. El capital de cada activo
crece con sus retornos diarios y su peso deriva con el mercado. Si se ingresa la cartera actual, la
rotación inicial es la mitad de la suma de diferencias absolutas de peso; un costo supuesto en puntos
base se aplica sólo a esa rotación inicial. Sin cartera actual, se supone que la cartera ya está en los
pesos iniciales y no se aplica costo. El cálculo no incluye spreads, impuestos, comisiones continuas,
liquidez ni ejecución real.

El resultado presenta retorno total neto, retorno anualizado neto según días naturales, volatilidad
anualizada con 252 sesiones, Sharpe realizado, máxima caída, rotación inicial y trayectoria de capital.
Las fechas y pesos usados se muestran para que se pueda comprobar que la evaluación no entró en la
estimación. Una sola fecha de corte es una comprobación de sensibilidad, no una validación robusta por
múltiples regímenes. Cambiar repetidamente la proporción después de observar los resultados puede
introducir sesgo por selección.

Los pesos iguales son un referente importante: el estudio de DeMiguel, Garlappi y Uppal halló que los
modelos de diversificación óptima basados en muestras no superaron consistentemente 1/N fuera de muestra
en sus siete conjuntos de datos. Este resultado motiva comparar el optimizador con una regla simple;
no determina cuál cartera conviene a un cliente concreto.

Fuente: [DeMiguel, Garlappi y Uppal, *Optimal Versus Naive Diversification*](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901?login=false).

## Revisiones sucesivas

El segundo panel conserva el corte inicial y revisa la asignación cada 3, 6 o 12 meses naturales.
Si la fecha prevista no tiene observación, opera en la primera sesión posterior y mantiene la
programación de calendario original. En cada revisión recalcula media y covarianza con una ventana
expansiva que termina en la sesión anterior; la sesión de la revisión y todas las posteriores quedan
fuera de esa estimación. El historial CSV indica fecha, última sesión utilizada, observaciones,
pesos, rotación y costo supuesto. Para evitar seleccionar retrospectivamente el mejor resultado,
conviene fijar corte, frecuencia, universo y costo antes de inspeccionar las curvas.

Cada estrategia invierte en los pesos calculados antes del retorno de la sesión. Entre revisiones,
las posiciones se mantienen y sus pesos cambian con el mercado. La rotación es la mitad de la suma
de cambios absolutos desde esos pesos efectivos; se descuenta del capital en puntos base al inicio
y en cada revisión. Pesos iguales se rebalancea en las mismas fechas. Si se proporciona la cartera
actual, ésta se compara como referencia sin rebalanceo; si no, se supone que la posición inicial ya
está asignada y su costo inicial es cero. El costo pagado acumulado se expresa como fracción del
capital inicial, no como suma de tasas ni como estimación de una tarifa real de la casa de bolsa.

Esta prueba supone retornos diarios continuos y ejecución al cierre indicado por los datos. No
modela spreads, impuestos, comisiones fijas, cambios de composición del universo, liquidez,
restricciones de lotes ni disponibilidad histórica de cada instrumento. Las tres frecuencias son
escenarios de investigación, no instrucciones operativas para un cliente.

Ambas pruebas pueden repetir la misma evaluación con una
[covarianza contraída hacia la diagonal](covariance_shrinkage.md). El 50 % es fijo y la
comparación comparte fechas, precios y costos; elegir el estimador después de mirar
el resultado fuera de muestra introduce sesgo de selección.
