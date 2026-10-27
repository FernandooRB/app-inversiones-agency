# Bitácora prospectiva en papel para SIC

La pestaña **Prueba en papel** dentro de Seguimiento registra señales observadas y operaciones
hipotéticas de **una acción** con cotizaciones locales MXN transcritas desde GBM. Nunca envía
órdenes ni consulta la cuenta del intermediario. Su propósito es reunir evidencia nueva sin
cambiar las reglas `tendencias-confirmadas-v1` después de ver los resultados. La revisión
retrospectiva anterior produjo sólo 12 operaciones y no estableció una ventaja fiable; véase
[la auditoría de robustez](technical_readiness_2026-10-26.md).

## Uso

1. Guarda los tickers en Seguimiento y pulsa **Actualizar señales**. En **Prueba en papel**, usa
   **Congelar la señal** para fijar sesión, señal, motivo, fuente, moneda e indicadores. Compra,
   Esperar y Venta pueden registrarse una sola vez por ticker, sesión y versión de regla.
   La hora de registro la asigna el servidor. Una señal No evaluable no se registra.
2. Sólo una señal **Compra** ya registrada permite una entrada simulada. En la siguiente sesión
   SIC disponible, transcribe serie e ISIN exactos, fecha/hora del libro de GBM, bid, ask,
   volumen, stop y objetivo locales. El precio de entrada supuesto es el ask. Confirma que
   corresponde a la siguiente sesión. La cotización debe tener como máximo 15 minutos al
   guardar el evento y ser posterior a la señal. No se rellenan precios del SIC con USD o FX.
3. Si quieres un contraste, registra al mismo tiempo el bid, ask, volumen, serie e ISIN de una
   **referencia que también opere en SIC**. Si no la capturas al entrar, la comparación queda
   pendiente: no se añade una referencia a posteriori al cerrar.
4. Para cerrar la operación ficticia, registra bid y volumen SIC actuales y el motivo de salida.
   Si se anotó una referencia al entrar, captura también su bid y volumen de salida. La bitácora
   conserva señal, entrada y salida como eventos separados sin opciones de edición o borrado.

Después de cada guardado, los contadores, formularios e historial se actualizan automáticamente.
La confirmación aparece en español con la hora UTC del registro. No hace falta recargar para
pasar de una señal Compra guardada a su entrada, ni de una entrada guardada a su salida.

El cálculo por acción es:

```text
retorno bruto = bid_salida / ask_entrada - 1
retorno neto = bid_salida × (1 − costo_lado) /
               [ask_entrada × (1 + costo_lado)] − 1
```

El costo adicional supuesto es 0.35 % por lado por defecto y es editable antes de registrar la
entrada. El bid/ask local incorpora el spread observado; el costo adicional representa cargos y
deslizamiento supuestos, **no** la tarifa contractual de GBM. La referencia usa la misma fórmula
y el mismo costo por lado durante el mismo intervalo. La tabla informa retornos por operación;
si hay pares completos, muestra la media de sus retornos y la diferencia en puntos porcentuales.
No es una curva de capital ni una comparación continua contra comprar y mantener. Las señales
sin operación también quedan visibles para evitar seleccionar retrospectivamente sólo aciertos.

## Límites y control de datos

La app no verifica de forma independiente el libro SIC transcrito, la disponibilidad real, la
profundidad ni si una cotización habría ejecutado una orden. Guardar una señal primero, exigir
una hora de cotización reciente, registrar la hora del servidor y prohibir cambios posteriores
reduce la edición retrospectiva, pero no convierte las capturas manuales en datos auditados.
Un stop puede ejecutarse a peor precio; la prueba no modela dividendos, impuestos, posición
agregada, efectivo no invertido ni liquidez total de una cartera. [Investor.gov](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)
explica por qué costos, método y selección de referencia importan al interpretar resultados.

En Supabase los eventos están en `public.technical_paper_events`, separados de las listas y del
registro de Expedientes. El servidor valida la identidad OIDC antes de consultar el hash
issuer/subject. La tabla tiene RLS habilitado; `anon` y `authenticated` carecen de permisos;
`service_role` sólo puede leer y añadir. En local, los eventos van a un SQLite privado distinto,
sin persistencia garantizada en Streamlit Community Cloud. El backend falla visiblemente si la
tabla no está disponible, sin degradarse a SQLite en producción. El SQL de creación está en
[`supabase/technical_paper_events.sql`](../supabase/technical_paper_events.sql).

Una prueba con dinero real sigue requiriendo una decisión sobre capital y pérdida máxima,
una serie SIC y tarifa verificadas, revisión de exposición y aprobación explícita de una orden
concreta. Esta bitácora por sí sola no desbloquea el envío de órdenes desde la app.
