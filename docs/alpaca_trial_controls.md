# Control y evaluación de la prueba Paper

La pantalla reúne límites, planes prospectivos de salida, avisos dentro de la app y resultados
por ejecución. Conserva las pruebas manuales separadas de las entradas con señal congelada previa.
Las órdenes siguen siendo limitadas DAY y requieren revisión y confirmación del usuario.

## Configuración de la prueba

En **Alpaca Paper → Control de la prueba**, el usuario guarda cuatro montos en USD: capital
asignado, presupuesto de pérdida prevista, límite por acción y pérdida prevista máxima por orden.
La pérdida total y el límite por acción deben caber en el capital; la pérdida por orden debe caber
en la pérdida total. No se eligen montos ni se activan límites automáticamente para el usuario.

El supuesto de fricción empieza en **0.35 % por lado**: costo de 0.25 % más escenario adicional
de deslizamiento de 0.10 % (10 puntos básicos). Es un escenario sobre precios ya ejecutados,
no un cargo confirmado por Alpaca. El usuario puede editarlo entre 0 % y 10 %.

El presupuesto incluye exposición de las posiciones largas al mayor entre entrada y precio
consultado, fricción supuesta, pérdida prevista al stop, compras pendientes y pérdida neta cerrada
del registro desde el inicio de la prueba. Las posiciones existentes se incorporan con su costo
original para este control; sus operaciones conservan su clasificación histórica. Las ganancias
cerradas compensan las pérdidas cerradas al calcular el presupuesto consumido, con mínimo cero.

Se consulta el conjunto de órdenes abiertas (hasta 499; con 500 se exige revisión en vez de
asumir que la respuesta está completa). Una compra pendiente sin precio/cantidad acotados bloquea
la ampliación. Se reserva conservadoramente la cantidad completa de una orden pendiente, incluso
si parte ya aparece en posiciones, porque las consultas del broker no son una transacción única.
Los intentos de la app aún no representados en esa consulta también consumen reserva.

La cantidad máxima se calcula con capital, límite por acción, presupuesto total y pérdida por
orden. Se vuelve a comprobar al confirmar. Los límites y el plan quedan capturados en el intento;
una revisión posterior exige preparar otra propuesta. La reserva atómica serializa las compras
concurrentes por usuario y cuenta mediante advisory lock en Postgres o transacción IMMEDIATE en
SQLite. El intento se guarda antes del POST. Un fallo de conexión conserva la conciliación por
el mismo identificador, sin repetir el envío.

Estas restricciones gobiernan las compras enviadas por la app según los datos consultados. Las
operaciones externas y los saltos de precio pueden alterar la exposición o superar la pérdida
prevista. El stop es una referencia, no una garantía de precio ni un límite absoluto de pérdida.
Las ventas que reducen posiciones largas conservan su confirmación manual aunque falten límites.

## Planes de salida

Cada plan guarda acción, referencia, stop, objetivo, motivo y fecha de revisión. Al crearlo se
exige stop < referencia < objetivo y una fecha desde el día de la bolsa. La revisión se expresa
en calendario; no se convierte silenciosamente en el horizonte de sesiones del backtest.

Las revisiones se añaden al historial con la fecha actual. Las posiciones que no tienen plan,
un plan vencido o un precio que alcanzó stop/objetivo deben revisarse antes de ampliar la prueba.
Una compra pendiente que quedó fuera de su plan también necesita revisión. Las referencias ATR
de una señal son auxiliares; presupuesto y avisos usan el plan vigente guardado. La protección
mediante órdenes stop/objetivo se gestiona manualmente en el panel del broker; esta entrega no
envía órdenes de protección, no cancela órdenes ni automatiza ventas.

## Ejecuciones y resultados

**Actualizar resultados** concilia hasta diez intentos por pulsación y descarga las actividades
FILL paginadas desde un día antes del primer intento. El token es el ID de la última actividad,
con 100 registros por página y máximo 5,000 ejecuciones. Repetición de página, error o exceso del
límite impiden declarar completa la descarga. Los intentos que fallan rotan para no bloquear
indefinidamente la consulta de los demás.

Cada fill conserva ID, orden, acción, lado, cantidad, precio y hora UTC. Las cantidades parciales
se aceptan aunque las órdenes solicitadas sean enteras. Se cotejan cantidades e importe promedio
contra la orden, con tolerancia de 0.0001 USD por título para el promedio del proveedor. Un ID
repetido no duplica operaciones; un ID con datos distintos exige revisión. Una huella y el número
de fills verifican la integridad de la descarga persistida antes de calcular.

FIFO consume las compras por hora individual de ejecución; los empates se resuelven por ID.
Las ejecuciones externas del periodo participan en el inventario, pero sólo los lotes de la app
reciben atribución en sus resultados. Inventario insuficiente o cantidades diferentes a Alpaca
dejan la conciliación pendiente. Faltantes anteriores al periodo y acciones corporativas pueden
requerir un historial adicional; no se inventa un costo para ellos.

Para una porción cerrada, el neto estimado es `venta × (1 − costo) − compra × (1 + costo)`.
El neto abierto supone liquidar al precio consultado con el mismo costo. Las métricas visibles
suman los importes por lote redondeados a centavos; las curvas usan precisión de cálculo. No se
incluyen dividendos ni impuestos y el cálculo no sustituye los estados del broker. Se exportan
resultados y fills individuales a CSV, conservando en estos últimos su precisión original.

## Alertas dentro de la app

El usuario eligió avisos dentro de la app. Se identifican cambios de señal, primera señal Compra
o Venta, datos vencidos/no evaluables, plan faltante/vencido, niveles alcanzados y exceso de
exposición. Se guardan sin sobrescribir la primera observación del aviso, se pueden marcar
revisados y conservan historial. Reconocer un aviso no desactiva un límite de compra.

**Actualizar señales y alertas** evalúa sesiones terminadas con el motor de señales existente.
El interruptor opcional consulta precios cada 60 segundos mientras la sesión de la app permanece
activa. Las señales se recalculan con el botón; se avisa si la consulta tiene más de una hora.
La cuenta se considera vencida para avisos tras 15 minutos sin consultar. Cada consulta verifica
autorización y configuración actuales. La app cerrada o dormida no mantiene vigilancia y no se
envían correos ni mensajes externos.

## Evaluación de entradas con señal

El resumen separa entradas con condiciones confirmadas antes de preparar de pruebas técnicas o
manuales. Conserva cantidades, operaciones cerradas, porcentaje ganador neto y resultado. Una
entrada se cuenta cerrada cuando no conserva títulos y su orden de entrada terminó; se identifican
las salidas que no tuvieron señal de venta. Una muestra pequeña se muestra como tal.

La comparación selecciona una acción y una revisión de presupuesto. Usa el límite por acción
capturado antes de las entradas como capital de referencia. Ambas alternativas compran inicialmente
la misma cantidad, pagan los mismos costos supuestos y conservan el efectivo restante. La prueba
incorpora después sus flujos; la referencia mantiene la primera entrada. Son resultados por
acción, no un índice ni la suma del capital de toda la cuenta.

La curva se calcula únicamente con cierres diarios terminados y sus flujos conocidos hasta cada
fecha. Exige historia desde la primera entrada, un presupuesto único y efectivo suficiente. Si
la primera entrada fue hoy, espera su primer cierre. La máxima caída usa cierres diarios e incluye
el capital inicial como máximo de partida; no mide la caída intradía. Dividendos e impuestos
quedan fuera de ambas alternativas y no se anualiza una muestra corta.

## Almacenamiento y verificación

La migración [alpaca_trial_controls.sql](../supabase/alpaca_trial_controls.sql) añade eventos
inmutables y dos funciones SECURITY INVOKER. Sólo el servidor tiene SELECT/INSERT y EXECUTE;
anon/authenticated no tienen acceso. Los secretos permanecen en Streamlit. Cada consulta filtra
por identidad OIDC verificada y UUID de cuenta. En local los controles comparten el archivo privado
de órdenes para que la comprobación y el reclamo usen una transacción. El límite de controles es
10,000 eventos por usuario/cuenta; requiere exportación administrativa si se alcanza.

La verificación incluye dos compras concurrentes contra el mismo capital, revisión de límites,
planes, fechas de bolsa, fills parciales/cancelados, deduplicación, costos, errores de paginación,
integridad, atribución externa y comparación de curvas. La prueba real de Postgres creó controles
sintéticos y comprobó rechazo de la segunda reserva, preservación del primer aviso y permisos;
se revirtió íntegramente. Los asesores de seguridad y rendimiento no reportaron hallazgos.

La suite local completó **640 pruebas** y Ruff pasó sin hallazgos. La revisión en Chromium a
1440, 768 y 390 píxeles comprobó formularios, avisos, resultados y comparación con datos
sintéticos, sin desbordamiento horizontal de la página. Las tablas anchas conservan su propio
desplazamiento; el aviso seleccionado también se presenta como texto para leerlo en móvil.
La gráfica usa fechas de sesión diaria y separa la leyenda de sus ejes. No se enviaron órdenes
al broker durante esta verificación. Los importes de las pruebas no activan límites en la cuenta
del usuario; la primera configuración de producción sigue pendiente de sus montos y planes.

Fuentes: [actividades Alpaca](https://docs.alpaca.markets/us/reference/getaccountactivities-2),
[órdenes abiertas](https://docs.alpaca.markets/us/reference/getallorders-1),
[reglas de órdenes](https://docs.alpaca.markets/us/docs/orders-at-alpaca) y
[funciones de Supabase](https://supabase.com/docs/guides/database/functions).
