# Sensibilidad USD/MXN con H.10 completo: AAPL/MSFT, enero-junio 2024

Ejecución local: 14 de septiembre de 2026, con `python -m scripts.validate_h10_live`.
Precios ajustados de AAPL/MSFT y `USDMXN=X` descargados de Yahoo mediante yfinance;
referencia independiente H.10 de la Reserva Federal en
`fx_reference_fed_h10_2024h1.csv`. La consulta a Yahoo es susceptible a revisiones
y límites del proveedor, por lo que las cifras siguientes se redondean.

## Muestra y supuestos

- Periodo solicitado: 1 de enero al 30 de junio de 2024.
- Precios comunes de AAPL/MSFT y ambas series FX: 124; retornos: 123.
- No hubo fechas de precios omitidas dentro del periodo comparable.
- Moneda base: MXN; pesos fijos de comparación: 30 % AAPL y 70 % MSFT.
- Tasa libre de riesgo supuesta: 3 % anual; VaR/CVaR: 95 % a 5 sesiones.
- Las dos columnas usan exactamente las mismas fechas y precios de acciones.
  El cambio aislado es la serie de conversión USD/MXN.

| Métrica histórica, pesos fijos | Yahoo FX | H.10 FX |
| --- | ---: | ---: |
| Media anualizada | 55.20 % | 52.49 % |
| Volatilidad anualizada | 21.67 % | 20.74 % |
| Sharpe | 2.409 | 2.386 |
| VaR histórico, 5 sesiones | 3.34 % | 2.96 % |
| CVaR histórico, 5 sesiones | 3.85 % | 3.81 % |
| Máximo Sharpe reoptimizado, AAPL/MSFT | 30 % / 70 % | 30 % / 70 % |

En las 124 fechas, la diferencia relativa media `Yahoo/H.10 - 1` fue -0.064 %.
Hubo ocho fechas con diferencia absoluta superior a 1 %. La mayor diferencia
absoluta fue 3.444 % el 3 de junio de 2024. Estas diferencias cambian métricas
de retorno y riesgo aunque las asignaciones óptimas de este caso no cambien.

## Interpretación y límites

La [serie H.10](https://www.federalreserve.gov/releases/h10/Hist/dat00_mx.htm)
corresponde a una tasa de compra de mediodía en Nueva York, según la
[metodología de la Reserva Federal](https://www.federalreserve.gov/releases/h10/about.htm).
El cierre de AAPL/MSFT ocurre más tarde. La hora y convención exacta de la serie
FX de Yahoo utilizada aquí no se confirmaron. Por eso **la discrepancia no prueba
que Yahoo esté equivocado ni que H.10 sea la tasa adecuada para valuar al cierre**.
No se desplazaron fechas ni se sustituyeron datos del análisis principal.

El ejercicio es una sensibilidad histórica sobre la misma muestra usada para
optimizar. No es un backtest fuera de muestra, un pronóstico ni una validación
externa completa de precios ajustados. El análisis principal y el PDF siguen
utilizando Yahoo. Antes de escoger una fuente principal para producción deben
definirse la hora de valuación, el calendario, la licencia de datos y una fuente
de precios de instrumentos adecuada para uso comercial.
