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

- Mientras el plazo disminuye exactamente los días naturales transcurridos, el factor diario es la razón
  entre precios consecutivos de la misma emisión.
- Si el plazo difiere de esa reducción, cambió la emisión representativa, incluso si el plazo disminuyó.
- Si la emisión anterior pudo vencer entre ambas fechas, se reconoce el pago del valor nominal.
- Si la referencia cambió antes del vencimiento, se rechaza el archivo. Precio y plazo de emisiones
  representativas distintas no revelan el precio de venta de la emisión anterior; un salto neutral habría
  introducido un retorno inventado. Para continuar se necesitan cotizaciones de la emisión específica.
- No se rellenan observaciones faltantes ni se calculan retornos directamente a partir de tasas.

La aplicación permite cargar un CSV con columnas `Fecha`, `Precio` y `Plazo`, más `Tasa` opcional
expresada en porcentaje anual (por ejemplo `6.5`, no `0.065`). Si existe, cada precio se contrasta
con la ecuación actual/360, con tolerancia de 0.0001 pesos por título. Las fechas deben usar
`YYYY-MM-DD` o `DD/MM/YYYY` de manera uniforme y no se descartan precios o plazos faltantes.
El nombre de la serie se agrega al final del orden de activos. La moneda base debe ser MXN y deben existir al menos 60
fechas comunes. Se aceptan recortes al inicio o final del periodo, pero se rechaza cualquier fecha de
mercado omitida dentro del intervalo común para no tratar retornos de varios días como diarios.

La aplicación muestra cuántos cambios de emisión por vencimiento reconoce y permite descargar el índice
preparado. Se transcribieron tres observaciones oficiales de CETES 28 días de CF300, del 10, 11 y
14 de septiembre de 2026: `(precio, plazo, tasa %) = (9.949391, 28, 6.539970)`,
`(9.951346, 27, 6.518917)` y `(9.956812, 24, 6.506299)`. La fórmula reproduce los precios
publicados y el plazo cae según los días naturales; **no aparecen cambios de emisión en este tramo**.
Esta comprobación puntual no valida toda la historia ni demuestra un rendimiento operable o neto.
Para una prueba de renovaciones reales se necesitan claves de emisión, fechas y precios de
venta y recompra por título. Los costos, impuestos, spread y reglas particulares del
intermediario se incorporarán después.

Fuentes:

- [Banxico SIE: precio, tasa y plazo de valores gubernamentales](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF300)
- [cetesdirecto: nota técnica de valuación de CETES](https://www.cetesdirecto.com/tablas/recursos/cetes_notaTecnica.pdf)
