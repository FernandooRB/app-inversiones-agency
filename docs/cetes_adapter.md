# Preparación de series de CETES

El módulo `fixed_income.py` prepara una serie de retorno total a partir de un archivo con fechas,
precio y plazo remanente. Acepta exportaciones CSV aportadas por el usuario y no requiere guardar un
token de la API de Banxico.

La valuación de control sigue la fórmula publicada por cetesdirecto:

\[
P = \frac{VN}{1 + r t / 360}
\]

donde `VN` es el valor nominal, `r` la tasa anual en decimal y `t` el plazo en días. La función
`cetes_price` implementa esta ecuación; una tasa de 10 % se ingresa como `0.10`.

## Construcción del índice

- Mientras el plazo disminuye, el factor diario es la razón entre precios consecutivos.
- Si el plazo aumenta, cambió la emisión representativa.
- Si la emisión anterior pudo vencer entre ambas fechas, se reconoce el pago del valor nominal.
- Si la referencia cambió antes del vencimiento, el cambio es neutral en esa fecha. Esto evita que la
  diferencia de precio entre dos CETES distintos aparezca como pérdida, aunque también omite el movimiento
  intradía de la fecha del cambio.
- No se rellenan observaciones faltantes ni se calculan retornos directamente a partir de tasas.

La serie resultante todavía requiere una revisión de sus fechas de cambio y su posterior unión con los
otros activos para entrar al optimizador. Los costos, impuestos, spread y reglas particulares del
intermediario se incorporarán después.

Fuentes:

- [Banxico SIE: precio, tasa y plazo de valores gubernamentales](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF300)
- [cetesdirecto: nota técnica de valuación de CETES](https://www.cetesdirecto.com/tablas/recursos/cetes_notaTecnica.pdf)
