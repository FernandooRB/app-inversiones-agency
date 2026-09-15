# Sensibilidad de las asignaciones a la muestra histórica

El panel reestima las carteras de máximo Sharpe y mínima volatilidad con toda la historia
disponible y con los últimos 60, 126 y 252 retornos, siempre que la ventana tenga menos
observaciones que la muestra completa. Todas terminan en la misma fecha. Mantiene la tasa
libre de riesgo y el límite por activo elegidos para el análisis principal.

La diferencia de pesos frente a la muestra completa es `0.5 × suma(|peso ventana − peso
completo|)`. Esa magnitud equivale a la rotación teórica para pasar entre dos asignaciones;
no incluye deriva de posiciones, precios de ejecución ni costos. El CSV contiene cada peso
por activo, ventana y objetivo. La tabla muestra el inicio, final, observaciones y activo de
mayor peso de cada estimación.

Una diferencia grande advierte que la asignación depende de la historia elegida. Una
diferencia pequeña tampoco demuestra que el modelo prediga retornos ni que convenga a un
cliente. Las ventanas se superponen y usan información ya observada; esto es un diagnóstico
de sensibilidad, no una validación fuera de muestra. Para evaluar comportamiento posterior,
usa las [pruebas de corte y revisiones sucesivas](backtesting.md) con parámetros fijados
antes de inspeccionar el resultado.
