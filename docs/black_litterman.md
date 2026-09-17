# Escenario Black-Litterman

La alternativa Black-Litterman reduce la dependencia directa de las medias históricas. Parte de
pesos de equilibrio declarados y calcula retornos implícitos en exceso como `δΣw`, donde `δ` es la
aversión al riesgo, `Σ` la covarianza anualizada y `w` los pesos de referencia. La tasa libre de
riesgo se suma para presentar retornos anuales totales.

El usuario puede añadir opiniones absolutas con el formato `activo, rendimiento anual %,
confianza %`. Cada activo admite una sola opinión y la confianza debe estar entre 1 % y 99 %. La
incertidumbre de la opinión se calcula a partir de `tau`, su varianza en la covarianza escalada y la
relación `(1-confianza)/confianza`. Una confianza mayor acerca más el posterior a la opinión; no
aporta evidencia de que la opinión sea correcta.

La cartera Black-Litterman maximiza Sharpe con los retornos posteriores, los mismos límites por
activo y clase, y la misma covarianza histórica de las demás alternativas. Esto conserva la
comparabilidad de volatilidad, VaR, estrés y atribución de riesgo. Los pesos de equilibrio,
parámetros, opiniones y resultados posteriores aparecen en la aplicación y el PDF.

Si no se ingresan pesos de equilibrio, se usa la cartera actual; si tampoco existe, se utiliza la
referencia simple factible. Si no hay opiniones, el posterior coincide con los retornos de
equilibrio implícitos. Ninguno de estos supuestos es un pronóstico verificado ni una asignación por
perfil de cliente.
