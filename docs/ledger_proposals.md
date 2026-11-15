# Del libro a una propuesta por títulos

En **Operación → Movimientos**, importa y revisa el libro de la cuenta. Las fuentes,
diferencias y confirmaciones de rendimiento conservan su alcance propio.

En **Implementación → Preparar desde el libro de movimientos** se muestran el corte
y el efectivo liquidado. Completa por instrumento precio sin ajuste, lote, peso objetivo
entre 0 y 1 y fuente del precio/lote. La fecha debe ser exactamente la del corte.
Puedes añadir instrumentos separados por coma; su cantidad inicial será cero.
Las cantidades existentes se reconstruyen desde el libro y no se editan en este paso.

Coteja la información y pulsa **Usar libro para preparar propuesta**. La app selecciona
el origen **Libro de movimientos** y conserva sus huellas y fuentes. Se mantiene
**CSV manual** como recorrido alternativo.

Revisa costos, IVA, comisión mínima, reserva de efectivo, rotación y concentración.
Documenta la tarifa y confirma los insumos antes de **Calcular propuesta de títulos**.
La salida compara cantidades iniciales y finales; el efectivo y los cargos conservan
las reglas de redondeo del motor existente. Esta acción prepara una propuesta y no
envía órdenes. La revisión y sus pendientes continúan abiertos.

La conexión rechaza cualquier evento pendiente de liquidación, aunque cobros y pagos
se compensen a cero; reportos vigentes; efectivo negativo; títulos o saldos en otra
moneda; instrumentos omitidos; fuentes vacías; fechas distintas; y pesos que superen 1.
No convierte reportos en efectivo ni supone un FX. Un modelo de riesgo reutilizado
debe pertenecer a esta cuenta y tener los mismos instrumentos y orden.

Cambiar origen, insumos, costos, límites o modelo retira la confirmación y la propuesta
anterior. Cambiar el libro/corte, reabrir una revisión o vaciar Movimientos exige
preparar nuevamente su conexión. Los datos se conservan en la sesión privada actual,
sin contratar almacenamiento. El ZIP financiero sigue leyendo las versiones 1 y 2.

**Descargar propuesta CSV** guarda el resultado por títulos. **Descargar insumos de
propuesta CSV** conserva posiciones, precios, lotes y pesos para volver a usar el
recorrido manual; el corte y las fuentes siguen documentados en la sesión y, cuando
esté habilitado, en la evidencia del expediente.

## Qué se guarda en el ZIP financiero

**Guardar borrador GBM** conserva también los CSV que ya existan en la revisión actual.
Si aún no hay libro, lo indica expresamente junto al siguiente paso. Un borrador sin
CSV puede contener los dos JSON internos y un resumen TXT; no significa que el libro
o el rendimiento estén terminados. El PDF se prepara por separado en **Archivos y
resumen descargable**. Los originales PDF/XML siguen fuera del ZIP.

## Práctica ficticia reproducible

El PDF de práctica declara 100 MXN iniciales, una aportación propia de 50 MXN al cierre
del 5 de enero y NAV de 100/150/150 en 2025-12-31, 2026-01-05 y 2026-01-30.
El control de 150.01 mantiene su diferencia de un centavo pendiente.

Para la propuesta ficticia se declara SIM-NEW a 10 MXN, lote 1 y peso 0.4; tarifa de
10 puntos base, mínimo 0, IVA 0 y costo de mercado 0. El resultado esperado es comprar
seis títulos, costo 0.06 y efectivo restante 89.94 MXN. Estos supuestos son de práctica,
no cotizaciones, lotes o tarifas reales de un intermediario.
