# Costo estimado de implementación

La aplicación compara el costo explícito de llevar efectivo o la cartera actual a cada asignación.
El cálculo es un escenario manual y usa la moneda base del análisis. Los valores iniciales son cero:
el equipo debe capturar los términos vigentes del contrato concreto.
Si algún supuesto es distinto de cero, también debe declarar una referencia y su fecha de consulta;
ambas aparecen en el PDF.
Como alternativa, el [perfil contractual de costos](broker_tariffs.md) importa en un solo CSV la
institución, producto, mercado, fecha, fuente y componentes transaccionales y recurrentes.

Por activo calcula la diferencia entre el importe objetivo y el importe actual. Cada diferencia
positiva es una compra y cada diferencia negativa es una venta. Para cada orden no nula aplica:

1. comisión: el mayor entre el nominal por la tasa ingresada y la comisión mínima;
2. IVA configurable, únicamente sobre la comisión estimada;
3. costo de mercado: nominal por el supuesto ingresado de medio spread, deslizamiento e impacto.

El resumen muestra compras, ventas, nominal total negociado y sus tres componentes de costo. Si no
se captura una cartera actual, supone que todo el capital parte de efectivo. Si se captura, cobra
por separado ambos lados del rebalanceo. Por ejemplo, cambiar de 40/60 a 70/30 compra 30 % y vende
30 %: el nominal negociado es 60 % del capital. Esto difiere de la rotación de media suma absoluta,
que sería 30 % y que las pruebas históricas conservan como convención estadística.

El cálculo mantiene fijo el nominal objetivo y presenta el costo como importe adicional. No resuelve
una lista de órdenes autofinanciada después de costos ni modela lotes, profundidad, límites de precio,
liquidación, custodia, cuotas mensuales, administración anual, tipo de cambio operativo, retenciones
o impuestos sobre ganancias. Tampoco determina si el IVA aplica a cada concepto del contrato.

Los costos recurrentes se mantienen fuera del costo inicial de las órdenes. La app estima por
separado el costo anual fijo más la administración anual sobre el capital, y suma ambos al costo
inicial para mostrar un total ilustrativo del primer año. Los valores recurrentes deben capturarse
después de los impuestos aplicables para evitar que la aplicación infiera tratamientos contractuales.

Antes de entregar un reporte, conserva el tarifario o estado de cuenta usado, su fecha de consulta,
el tipo de cliente y el producto. No extrapoles una tarifa de acciones a fondos, deuda o divisas.
