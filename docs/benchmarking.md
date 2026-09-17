# Comparación histórica contra benchmark

La aplicación permite declarar un ticker independiente como benchmark. Se descarga su precio ajustado,
se declara su moneda de cotización y se convierte a la misma moneda base que la cartera. Después se
intersectan las fechas sin rellenar observaciones. Se requieren al menos 60 retornos comunes.

El benchmark no se añade al universo invertible ni altera la optimización. Puede ser un índice para
medir el mercado o un vehículo negociable elegido como referencia; si se pretende invertir en él debe
identificarse el instrumento concreto, sus costos y su disponibilidad.

Para cada alternativa se calculan:

- retorno total y retorno geométrico anualizado de cartera y benchmark;
- retorno activo anualizado como la media diaria de `cartera - benchmark`, multiplicada por 252;
- tracking error como la desviación estándar anualizada de esos retornos activos;
- razón de información como retorno activo anualizado dividido entre tracking error;
- beta como covarianza de cartera y benchmark dividida entre la varianza del benchmark;
- alpha anualizada mediante CAPM con la tasa libre de riesgo configurada;
- correlación diaria y máxima caída de ambas trayectorias.

Para hacer comparables las alternativas, el retorno diario de cada cartera usa pesos constantes, lo
que equivale a rebalanceo diario. Por ello esta atribución puede diferir de una cartera buy-and-hold o
de una política de rebalanceo trimestral, semestral o anual. No descuenta costos ni impuestos.

La selección del benchmark requiere criterio: debe guardar relación con la moneda, mercado, universo
y riesgo de la cartera. Comparar una cartera diversificada con un índice estrecho puede producir alpha,
beta o razón de información poco útiles. Los resultados son descriptivos de la muestra; no prueban
habilidad, causalidad ni persistencia futura.
