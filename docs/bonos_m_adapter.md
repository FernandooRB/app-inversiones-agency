# Preparación de series de Bonos M

La aplicación acepta un CSV revisable para **una sola emisión** de Bono M. No utiliza una tasa de
rendimiento como si fuera retorno diario y no mezcla bonos representativos con vencimientos distintos.

Las columnas requeridas son:

- `Fecha`: `YYYY-MM-DD` o `DD/MM/YYYY`, con un solo formato en el archivo;
- `Emision`: identificador constante de la emisión;
- `Vencimiento`: fecha constante en formato `YYYY-MM-DD`;
- `PrecioLimpio`: precio por 100 de valor nominal;
- `InteresDevengado`: interés acumulado por 100 de nominal;
- `Cupon`: efectivo recibido por 100 de nominal entre la observación anterior y el cierre de la fecha.

Si el archivo incluye una fila con fecha de vencimiento, añade `Amortizacion` con el capital
pagado por 100 de nominal. En esa fila, registra el cupón final y el capital por separado,
con precio limpio e interés devengado en cero al cierre después del pago. Registra `0` en
`Amortizacion` en todas las fechas anteriores. Si falta el pago documentado, el archivo puede
terminar en la última cotización previa al vencimiento. Los CSV que terminan antes del vencimiento
siguen admitiendo las seis columnas originales.

El precio sucio es `PrecioLimpio + InteresDevengado`. Para cada fecha posterior a la primera, el
factor de retorno total es:

`(PrecioSucio_t + Cupon_t + Amortizacion_t) / PrecioSucio_(t-1)`

El cupón de la primera fila debe ser cero porque no existe una observación anterior dentro de la
muestra a la cual atribuirlo. El índice inicia en 100. El archivo se rechaza si mezcla emisiones o
vencimientos, contiene fechas posteriores al vencimiento, valores faltantes, precios no positivos
antes del vencimiento, interés o cupones negativos, o unidades fuera de los límites de control.
La amortización de un Bono M al vencimiento debe coincidir con el valor nominal. El registro del
principal sigue la estructura de pago de los [Bonos M documentada por cetesdirecto](https://www.cetesdirecto.com/tablas/recursos/bonos_notaTecnica.pdf).

Al combinarlo con acciones, ETF o CETES se permiten recortes al principio o final del periodo, pero
se rechazan huecos en las fechas de mercado dentro del intervalo común. Si la fecha de amortización
queda fuera del calendario común, la aplicación lo indica y conserva el pago en la auditoría de la
serie por emisión. La aplicación conserva la
huella SHA-256, emisión, vencimiento y número de cupones reconocidos en la sesión y en la fuente
documentada del PDF. También permite descargar precio limpio, interés, precio sucio, cupones, amortización e índice
preparado para auditoría.

El adaptador no verifica de forma independiente la fuente, la convención exacta de devengado, el
calendario de pagos, impuestos, spread, liquidez ni derechos de uso. Esos extremos deben comprobarse
contra la emisión y el proveedor antes de distribuir resultados.
