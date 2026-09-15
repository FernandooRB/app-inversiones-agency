# Validación fuera de muestra con una fecha de corte

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
