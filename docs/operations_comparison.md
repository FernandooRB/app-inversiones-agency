# De una estrategia a títulos comparables

En **Análisis de cuenta**, calcula y revisa una alternativa. En **Operación →
Implementación**, prepara el libro o carga posiciones con precios sin ajuste y
lotes. En **Pesos objetivo**, elige la alternativa del análisis. La conexión exige
la misma cuenta e identidad, corte, moneda MXN e instrumentos en el mismo orden.
Los cambios sin calcular del análisis impiden usarlo.

Se muestran los pesos y la ejecución de origen. Son objetivos sobre todo el capital
disponible, incluido el efectivo. Los precios ajustados del análisis permanecen
como historia; las órdenes estimadas usan los precios sin ajuste y las tarifas
revisados en Implementación. Confirma esos datos antes de calcular.

**Calcular propuesta de títulos** prepara la propuesta con lotes. **Comparar
alternativas con estos insumos** muestra:

- **Conservar:** los mismos títulos y efectivo, sin cargos de transacción.
  Un incumplimiento previo de concentración o reserva permanece visible.
- **Cambio parcial:** un acercamiento configurable del peso actual al objetivo,
  antes de calcular títulos por lote. Su porcentaje inicial es 25%.
- **Propuesta:** el objetivo completo sujeto a efectivo, lotes, tarifas,
  concentración, importe mínimo y rotación. Una alternativa inviable conserva
  su motivo y sus cifras no se convierten en cero.

La propuesta vigente se reutiliza al comparar cuando coinciden sus insumos y
límites; su validación aritmética no vuelve a resolverla. Navegar y descargar no
ejecutan optimizadores. Los costos recurrentes y los impuestos de una venta no se
suponen incluidos en los cargos de estas órdenes.

## Qué mide el riesgo

Los pesos se recalculan con los títulos finales y el patrimonio **después de los
cargos**, conservando el efectivo como parte de ese patrimonio. La tabla muestra
media y volatilidad anualizadas del modelo disponible, con su estimador, periodo
y observaciones. En el detalle se encuentra la cobertura de títulos y el peso del
efectivo.

El modelo supone que el efectivo permanece constante en términos nominales; no
atribuye a ese supuesto cobertura de inflación, divisas o contraparte. Si falta un
análisis compatible o historia suficiente, el riesgo queda **pendiente**.
Estas cifras describen una exposición al modelo, no una ganancia futura ni el
rendimiento histórico del libro.

## Guardar y retomar

Descarga el CSV comparativo por separado. El PDF de propuesta se prepara bajo
demanda y muestra su estrategia y periodo de origen. El ZIP v4 conserva propuesta,
pesos efectivos y procedencia del análisis: ejecución, versión, universo, fechas y
huellas de sus insumos. No incluye los PDF/XML originales ni restaura aprobaciones.
Los ZIP v1, v2 y v3 siguen legibles.

Al reabrir puedes elegir **Pesos guardados**, los **Pesos del insumo**, o una
alternativa de un análisis vigente. Los pesos guardados de un libro permanecen
vinculados a su libro, corte, moneda y orden de instrumentos. Cambiar a una moneda
o fecha incompatible exige revisar otro origen de pesos antes de calcular. Volver
a confirmar el puente del libro conserva la procedencia aunque sus campos se
precarguen con los pesos efectivos recuperados.

Para evaluar riesgos otra vez, abre también el análisis de cuenta. El paquete de
propuesta conserva el objetivo y su resultado histórico; no inventa las series
que faltan. Cambiar los insumos relevantes retira los resultados y las
confirmaciones anteriores. Ninguna de estas acciones envía órdenes.
