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

## Intensidad calibrada con historia anterior

Una tercera opción selecciona entre 0 %, 25 %, 50 %, 75 % y 100 % sin mirar la evaluación
externa. Exige al menos 100 retornos iniciales. Dentro de esa historia se usan bloques
cronológicos de 20 retornos: se estima con los primeros 60, 126 y 252 retornos cuando
existen, y con el prefijo anterior al último bloque disponible; se omiten bloques
superpuestos. Para cada intensidad se compara la covarianza estimada con la covarianza
realizada en el bloque siguiente mediante suma de errores cuadrados de matriz. Se elige
el menor error promedio; un empate favorece la menor contracción. Las fechas y errores
de cada bloque se muestran para el corte único.

En revisiones sucesivas se repite esa selección con la historia que termina el día anterior
a cada rebalanceo. El CSV registra la intensidad usada en cada fecha. La medida de error
no optimiza rendimiento ni Sharpe; tampoco garantiza menor riesgo futuro. Los bloques
son pocos y de 20 sesiones, por lo que la elección puede ser ruidosa. Este protocolo
cronológico es propio del piloto, no una implementación de LOOCV ni del estimador
analítico de Ledoit–Wolf.

La contracción es una familia de estimadores reconocida para matrices de covarianza difíciles
de estimar; el estudio de Ledoit y Wolf describe su motivación estadística. La fórmula de este
piloto y su intensidad fija son decisiones propias del proyecto, no el estimador óptimo del
artículo.

Fuente: [Ledoit y Wolf, *A Well-Conditioned Estimator for Large-Dimensional Covariance Matrices*](https://www.ledoit.net/Well-conditioned2004.pdf).
Relacionado: [Tong y otros, *Linear Shrinkage Estimation of Covariance Matrices Using Low-Complexity Cross-Validation*](https://arxiv.org/abs/1810.08360).
