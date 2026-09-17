# Atribución de riesgo y diversificación

La aplicación descompone la volatilidad anualizada de cada alternativa mediante la identidad de
Euler. Para pesos `w`, covarianza anualizada `Σ` y volatilidad `σ`, la contribución del activo `i` es
`wᵢ(Σw)ᵢ/σ`. La suma de las contribuciones con signo reconcilia exactamente con `σ`.

Una contribución negativa se conserva porque indica que el activo reduce la volatilidad conjunta
dentro de la covarianza estimada. Para medir concentración se usa por separado la participación
absoluta de cada contribución; así, una cobertura no cancela artificialmente la concentración de
otros activos.

El diagnóstico también muestra:

- razón de diversificación: suma ponderada de volatilidades individuales dividida entre la
  volatilidad de la cartera;
- posiciones efectivas: inverso de la suma de pesos al cuadrado;
- contribuyentes efectivos de riesgo: inverso de la suma de participaciones absolutas de riesgo al
  cuadrado;
- mayor contribuyente absoluto de riesgo.

Estas cifras describen el modelo histórico y dependen de la muestra, la moneda base y el estimador
de covarianza. No son límites de pérdida ni predicciones. La tabla completa puede descargarse como
CSV y el PDF conserva un resumen por alternativa.
