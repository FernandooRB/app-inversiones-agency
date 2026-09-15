# Comparación de covarianza muestral y diagonal

El análisis principal conserva la covarianza muestral. En las dos pruebas fuera de muestra
puede compararse con una contracción fija del 50 % hacia una matriz diagonal:

`Σ_50 = 0.5 × Σ_muestral + 0.5 × diag(Σ_muestral)`.

El cálculo conserva la varianza de cada activo y reduce a la mitad las covarianzas estimadas
entre activos. La pequeña regularización numérica que ya usa el motor se añade después, de
igual forma en ambos escenarios. Las medias históricas, la tasa libre de riesgo, el universo,
las fechas, las restricciones y los costos supuestos permanecen iguales. Se comparan máximo
Sharpe y mínima volatilidad; pesos iguales ofrece un referente idéntico entre estimadores.

El 50 % fue elegido como escenario de sensibilidad fácil de auditar. No es una intensidad
estimada automáticamente ni una implementación de Ledoit–Wolf. Reducir correlaciones
estimadas puede mejorar la estabilidad numérica, pero también puede borrar dependencias
económicas reales; por eso se muestran los resultados fuera de muestra sin seleccionar el
mejor después de observarlos. Conviene fijar el estimador antes de estudiar un periodo de
evaluación y repetir la comprobación en otros regímenes y universos.

La contracción es una familia de estimadores reconocida para matrices de covarianza difíciles
de estimar; el estudio de Ledoit y Wolf describe su motivación estadística. La fórmula de este
piloto y su intensidad fija son decisiones propias del proyecto, no el estimador óptimo del
artículo.

Fuente: [Ledoit y Wolf, *A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices*](https://www.ledoit.net/Well-conditioned2004.pdf).
