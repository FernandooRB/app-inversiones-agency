# Desglose documentado y comparación de cortes

Entrega de los puntos 15–16. Los datos reales continúan en local; las pruebas y
ejemplos publicados son ficticios. El alojamiento continúa en USD 0.

## Qué se puede hacer

En **Operación → Movimientos**, prepara el libro y revisa las fuentes de cierre.
En **Cuánto gané y por qué → Ingresos, cargos y detalle del rendimiento** puedes
ver ingresos, cargos e impuestos por instrumento, en su moneda original. Los
importes en monedas distintas no se suman ni se convierten sin fuente.

Abre **Comparar y guardar cortes** y descarga **corte actual JSON**. En una revisión
posterior, aporta ese archivo como **corte anterior JSON**. Coteja la cuenta y las
fuentes y confirma otra vez. Una fecha igual compara versiones; una fecha posterior
permite atribuir el cambio temporal si se conserva el historial previo.

La comparación conserva títulos, efectivo liquidado, pendientes de liquidación,
principal de reportos, pesos sobre patrimonio neto, incidencias y fuentes distintas.
El CSV incluye todas las filas; las tablas muestran como máximo 100 filas. Los
TWR/XIRR guardados se muestran con su propio periodo, sin restarlos para construir
un rendimiento nuevo. Los pesos se muestran como porcentajes; el CSV conserva
sus fracciones exactas y los saldos negativos, cuando corresponden.

El PDF breve y el resumen TXT incorporan la comparación de la misma ejecución
mientras mantengas abierto el panel de comparación y sus archivos vigentes.
El CSV conserva su detalle. **El ZIP de movimientos sigue siendo el archivo para
continuar la revisión**; el JSON conserva un estado histórico para compararlo,
no sustituye el ZIP ni restablece autorizaciones. Guardar y reabrir ZIP v1–v4 no
cambia. Para conservar esta comparación, descarga también sus JSON/CSV/TXT.

## Cálculos y alcance

- Ganancia entre cortes = patrimonio final − inicial − aportaciones + retiros.
  Usa el patrimonio del libro, que incluye efectivo pendiente. Los movimientos
  externos se sitúan por fecha de operación para este puente patrimonial. No es
  TWR; el recorrido existente de TWR/XIRR conserva sus fechas y requisitos propios.
- Precio por instrumento, en moneda de origen = valor final − inicial − compras
  brutas + ventas brutas − entradas en especie + salidas en especie. El valor de
  una entrada/salida en especie procede de cantidad × precio declarado. No se
  inventa costo fiscal, precio de adquisición ni ganancia fiscal realizada.
- Dividendos, cupones, intereses, comisiones e impuestos se identifican por fecha
  de operación: el libro ya reconoce su contrapartida pendiente antes de liquidar.
  Esto corrige el criterio anterior de desglose por liquidación. Liquidar no vuelve
  a generar ingreso ni precio. El monto bruto del reporto incluye principal; sólo
  `Interes` identifica el ingreso cobrado.
- En tenencias en divisa sin movimientos monetarios, precio = cambio de valor
  nativo × FX final; divisa = valor nativo inicial × cambio de FX. Es una convención
  aditiva explícita, no una recomendación de inversión. Los reportos muestran su
  variación de valuación separada del interés y del principal.
- Con operaciones en divisa sin FX de cada operación, el precio nativo puede
  seguir disponible, pero la atribución en moneda base queda pendiente. Los flujos
  externos en divisa también impiden declarar una ganancia base sin su FX fechado.
  Las tasas de un cierre no se propagan a otros días.
- Variación no desglosada = ganancia menos componentes cubiertos, sumando de nuevo
  cargos e impuestos cubiertos. Los componentes incompletos permanecen dentro de
  esa variación; no se interpretan como cero. El centavo nunca se ajusta para cuadrar.
  Si un componente está incompleto, su subtotal documentado se conserva y se
  excluye del residual, aunque el total siga pendiente por las piezas sin FX.
  El resumen previo al cotejo de cortes muestra el **resto tras ingresos y cargos**:
  ese resto todavía incluye precios y divisas, aunque la comparación pueda explicarlos.

Ejemplos independientes ficticios: aportar 50 a 100 y terminar con 150 produce
ganancia 0. Comprar por 20 y vender por 24 aporta 4 por precio; dividendo 3 menos
comisión 1 e impuesto .30 deja 5.70. Una posición estática de 10 títulos USD10→12,
con FX20→21, pasa de MXN2000 a 2520: precio420 + divisa100 = ganancia520.

## Integridad y privacidad

El corte es JSON de datos, esquema 1, máximo 2 MB, hasta 20,000 movimientos,
1,000 incidencias y siete huellas de CSV. Conserva fechas, cantidades y decimales
como datos independientes de las clases de Python. Se rechazan campos desconocidos,
claves JSON duplicadas, fechas futuras de corte, importes no finitos, valuaciones
incoherentes, mezcla de cuentas/monedas y huellas alteradas. Se valida el historial
con el mismo motor del libro. Las huellas detectan cambios; no prueban autoría ni
exactitud documental. Siempre corresponde cotejar los originales localmente.

Los archivos descargados contienen datos privados sin cifrar. El corte no incluye
PDF/XML, contraseñas, tokens ni una autorización reutilizable. Reemplazar un archivo,
cambiar una fuente o abrir otra revisión retira la confirmación de comparación.
Un corte rechazado no reemplaza el libro. Las exportaciones CSV neutralizan fórmulas
en identificadores. No se crean ajustes contables, órdenes ni movimientos nuevos.

## Pendientes que esta entrega no resuelve con supuestos

Valuaciones reales de julio, valor del reporto, transferencias desconocidas, evento
GMéxico y tarifas reales requieren evidencia. La atribución intradía en divisas,
atribución fiscal y nuevos intermediarios conservan su alcance pendiente. La
reapertura ya informada en Samsung S23/Chrome es autoinforme, no observación del
recorrido completo ni prueba de comprensión. Las auditorías automáticas y humanas
se registran por separado en cada informe de entrega.

Verificación reproducible: `pytest tests/test_performance_cuts.py`, regresión total,
`ruff check .`, y `node scripts/check_operations_browser.cjs` con Playwright/axe y
`SIG_PYTHON` apuntando al entorno del proyecto. `SIG_CUTS_ONLY=1` limita el navegador
al recorrido ficticio nuevo. Linux, contenedor y publicación se acreditan únicamente
cuando existan sus registros, no por esta guía.
