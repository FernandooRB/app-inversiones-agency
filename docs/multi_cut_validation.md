# Sensibilidad a cuatro fechas de corte

El panel ejecuta cuatro cortes cronológicos fijados en el código: estima con el primer
50 %, 60 %, 70 % y 80 % de los retornos y evalúa cada asignación en el tramo posterior.
Exige al menos 120 retornos diarios comparables; la opción de covarianza calibrada
requiere 200 para que el primer corte contenga 100 observaciones de entrenamiento.
Las estrategias compran al inicio de cada evaluación y mantienen posiciones sin
rebalancear, como en la [prueba de corte único](backtesting.md).

Cada fila muestra las fechas y tamaños de sus dos ventanas, la intensidad de
contracción de covarianza utilizada y métricas netas. La diferencia frente a pesos
iguales resta rendimientos medidos en **el mismo tramo** de evaluación. Si se introduce
la cartera actual, el costo supuesto se descuenta únicamente de la rotación inicial;
sin ella se supone que la posición ya está asignada. La aplicación permite ver la
trayectoria de un corte y descargar pesos y resultados de los cuatro.

Los tramos de evaluación tienen duraciones diferentes y se solapan. No son cuatro
experimentos independientes: no se suman rendimientos, se promedian Sharpe ni se
estima una probabilidad de superar al referente a partir de ellos. El ejercicio
detecta sensibilidad a la fecha de corte elegida, pero no elimina sesgos por el
universo de activos, la calidad de datos, los parámetros seleccionados después de
ver resultados o las condiciones de ejecución. Conviene fijar el universo, el
estimador y el costo antes de interpretar los cuatro cortes.

Como contexto metodológico, [CFA Institute: *Backtesting & Simulation*](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation)
describe la utilidad de complementar backtesting con análisis de sensibilidad.
Los cuatro cortes y las reglas de comparación aquí descritas son decisiones del proyecto.
