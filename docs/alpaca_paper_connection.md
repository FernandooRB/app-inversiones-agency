# Conexión privada con Alpaca Paper

En **Seguimiento → Alpaca Paper**, la primera entrega consulta una cuenta de simulación,
sus posiciones abiertas y hasta las 50 órdenes más recientes de todos los estados. El botón
**Conectar y consultar** comprueba las credenciales y carga la cuenta. **Actualizar cuenta**
repite la consulta. La hora UTC identifica la última respuesta completa; la pantalla no es un
monitor continuo. La pestaña **Orden limitada de prueba** permite preparar y confirmar una
solicitud Paper y consultar después su ejecución. La cancelación se realiza en el panel de Alpaca.

La cuenta corresponde al mercado de origen y a importes USD. Esta vista es independiente de
la bitácora manual SIC/GBM en MXN y no cambia la fuente Yahoo/yfinance de las señales.

## Señales de origen y resultados

La pestaña **Resultados y señales** muestra los lotes comprados desde esta app, la cantidad
abierta, el resultado por precio abierto/cerrado y la señal que se eligió antes del envío.
Las órdenes antiguas sin referencia se conservan como pruebas técnicas; no se les asignan
señales calculadas o guardadas después. Las compras iniciales de NVDA quedan en esta categoría.

Para una nueva prueba:

1. Añade el ticker en Seguimiento y actualiza sus señales.
2. En **Prueba en papel**, congela la observación. Esto guarda sus condiciones y, cuando está
   disponible, el ATR14. La captura no abre una posición SIC ni una orden Alpaca.
3. En **Alpaca Paper → Orden limitada de prueba**, elige ese ticker y la señal congelada de
   referencia. Prepara la propuesta y revisa su clasificación antes de confirmar.
4. En **Resultados y señales**, pulsa **Actualizar resultados**. Consulta la cuenta y concilia
   hasta diez intentos pendientes por pulsación mediante GET, guardando sus respuestas sin
   enviar órdenes. Comprueba la identidad/configuración actuales y la misma cuenta antes de
   guardar observaciones. Un error parcial conserva el estado anterior y muestra el motivo;
   si quedan más intentos, indica que hay otro lote por consultar.

La referencia debe pertenecer al mismo usuario y ticker, tener moneda USD y haberse guardado
antes de preparar la propuesta. Se vuelve a leer antes del POST. Su contenido queda dentro
del intento inmutable en Supabase/SQLite, separado de los datos enviados al broker. Cambiar la
referencia invalida la revisión anterior. Una señal Esperar, antigua (más de cinco días
naturales), de otra versión o sin todas las condiciones confirmadas se etiqueta como prueba
manual; no cuenta como confirmación de la estrategia. Incluso una coincidencia es evidencia
de cumplimiento de reglas, no una probabilidad de beneficio ni una evaluación de idoneidad.

Para compras con ATR14 guardado, stop = entrada − 2 ATR y objetivo = entrada + 4 ATR.
La revisión usa el límite y los resultados recalculan con el precio ejecutado. Son referencias;
esta función no envía órdenes stop/objetivo. Las observaciones antiguas sin ATR muestran
niveles ausentes en lugar de reconstruirlos con información futura.

Los resultados usan Decimal y un modelo FIFO de **órdenes completamente ejecutadas**, ordenadas
por su hora de finalización, con el precio medio de cada orden. No reconstruyen la secuencia
de cada fill individual. Se muestran por lote, antes de comisiones, dividendos e impuestos;
no son un cálculo fiscal ni el rendimiento completo de Alpaca. Las compras abiertas se valoran
con el precio de la última consulta de la cuenta, no con el cierre de Yahoo. No se mezcla USD
con MXN ni se suma el saldo inicial de Paper al resultado de la estrategia.

Las ejecuciones parciales, ventas sin compras suficientes y horas de finalización ausentes
producen una limitación visible para ese símbolo. Las órdenes antiguas necesitan una nueva
consulta del intento para guardar `filled_at` si se quieren reconstruir sus cierres. Un
descuadre entre cantidades abiertas y la cuenta, o una orden ejecutada fuera del registro entre
las últimas 50 órdenes, deja el resultado abierto sin calcular. Las limitaciones bloquean los
totales agregados para evitar presentar un total incompleto como completo. Los lotes completos
de otros símbolos siguen visibles con su alcance declarado. La detección de órdenes externas
no sustituye un historial completo de actividades de la cuenta.

No se requiere otra tabla ni modificar Secrets: la referencia se incorpora al JSON del intento
existente, con los mismos controles de identidad y cuenta y sin sobrescribir registros previos.

Validación de esta ampliación: suite local completa de 605 pruebas antes de los últimos cuatro
casos de recuperación, seguida de 49 pruebas focalizadas y 22 tras el ajuste de presentación;
Ruff y comprobación de parche correctos. Se probaron persistencia, aislamiento, referencias
posteriores o alteradas, cambio de referencia, ATR ausente/inválido, reconstrucción FIFO, cierres
parciales de un lote, órdenes parcialmente ejecutadas y discrepancias con la cuenta. Las pruebas
usan cuentas sintéticas y MockTransport, sin enviar nuevas órdenes a Alpaca del usuario.

La conciliación agrupada se verificó además con errores parciales, límite por lote y cuenta
cambiada, comprobando que sólo hace GET al broker y conserva los intentos existentes.

La revisión visual mantuvo SIG y la dirección existente `achromatic-ledger` (semilla 1942259728),
sin redibujar el shell. Las capturas locales a 1440, 768 y 390 px mostraron el resultado como
figura principal, cantidades enteras, números alineados y desplazamiento interno de la tabla
sin desbordamiento horizontal de página. Se adelantaron resultado/cantidad sobre los IDs y se
acortó la selección del intento. Los importes de revisión son sintéticos. El asesor de seguridad
de Supabase no reportó hallazgos; esta ampliación no altera permisos ni estructura de tablas.

## Configuración en Streamlit Community Cloud

1. En el panel de Alpaca, elige **Paper Trading** y genera las dos **API Keys** de esa cuenta.
   La clave secreta debe guardarse cuando se genera; si se pierde, hay que generar unas nuevas.
2. Abre la app en Streamlit Community Cloud y entra en **Settings → Secrets**. Conserva los
   bloques de autenticación, acceso y Supabase existentes.
3. Añade este bloque, sustituyendo los ejemplos. Copia `owner_issuer` y `owner_subject` de
   **tu propia** identidad ya autorizada en `[[access.identities]]`; no de otro usuario.

```toml
[alpaca_paper]
enabled = true
owner_issuer = "https://accounts.google.com"
owner_subject = "COPIAR_EL_SUBJECT_DE_TU_IDENTIDAD_AUTORIZADA"
api_key = "API_KEY_DE_TU_CUENTA_PAPER"
secret_key = "SECRET_KEY_DE_TU_CUENTA_PAPER"
# Opcional, para fijar la cuenta esperada después de verificar su identificador:
# expected_account_id = "UUID_DE_TU_CUENTA_PAPER"
```

4. Guarda, recarga la app, inicia sesión y abre **Seguimiento → Alpaca Paper**.
5. Pulsa **Conectar y consultar** y compara los importes y la cuenta con el panel de Alpaca.
   Una cuenta nueva puede no tener posiciones ni órdenes: esos estados vacíos son válidos.
6. El UUID de cuenta se encuentra en **Identificación y alcance de esta conexión**. Se puede
   copiar a `expected_account_id` para que futuras consultas rechacen otra cuenta Paper.

Las claves van sólo en Secrets del servidor. No se pegan en el chat, en formularios de la app,
en Git ni en Supabase. Esta primera versión conecta una cuenta Paper a un único propietario
OIDC; los demás usuarios de la app no reciben acceso a ella. Para ofrecer cuentas separadas
a muchos usuarios hará falta una integración de autorización por usuario.

## Controles y errores

- El adaptador consulta `https://paper-api.alpaca.markets` y sólo permite POST de órdenes
  limitadas DAY, simples y sin horario extendido. Las redirecciones están deshabilitadas y
  no existe un selector de servidor live. No permite ventas en corto ni órdenes fraccionarias.
- La app comprueba autorización OIDC, expiración y propietario antes de construir el cliente.
- Las claves reales de inversión y las claves Paper son diferentes. Si el servidor rechaza
  las credenciales, la vista muestra un error sin imprimir claves ni el cuerpo del proveedor.
- Se validan moneda, identificadores, importes finitos, restricciones y fechas. Si falla parte
  de la consulta, no se presenta una actualización parcial como completa.
- Al fallar una actualización se conserva la última consulta correcta con su hora y aviso.
  Al cambiar usuario, credenciales o cuenta esperada se descartan los datos de sesión previos.
- Los datos de cuenta no se guardan en una caché compartida ni se añaden a la bitácora SIC.
- El poder de compra puede incluir margen. Los campos de cantidad o precio que falten se
  muestran vacíos, y los ceros reales se conservan como ceros. Las ejecuciones parciales se
  muestran con la cantidad realmente ejecutada.

## Qué valida esta fase

La verificación con respuestas sintéticas cubre el servidor de destino, métodos GET,
credenciales, rechazo de redirecciones, errores, valores faltantes, límites de órdenes,
aislamiento entre usuarios, rotación de claves y navegación. El acceso efectivo a la cuenta
del usuario se valida al configurar Secrets y comparar el resultado con el panel de Alpaca.

## Preparar, confirmar y seguir una orden Paper

1. Conecta y compara tu cuenta con el panel de Alpaca. Abre **Orden limitada de prueba**.
2. Escribe el símbolo, Compra o Venta, títulos enteros y precio límite USD. Pulsa
   **Preparar propuesta Paper**. Esta acción consulta datos; todavía no envía la orden.
3. Revisa cuenta, símbolo, lado, cantidad, límite, importe y horario. La revisión vence en
   cinco minutos y se descarta si cambias sus entradas o las credenciales.
4. Marca la confirmación que describe esa propuesta y pulsa **Confirmar y enviar a Paper**.
   La app vuelve a comprobar disponibilidad, restricciones, instrumento y horario. Las compras
   se limitan al menor entre efectivo, poder de compra y poder disponible sin margen
   (`non_marginable_buying_power`), incluyendo reservas comunicadas por Alpaca; las ventas requieren títulos
   largos disponibles (`qty_available`), descontadas las reservas informadas por Alpaca.
5. El estado inicial puede ser aceptada o pendiente. Revisa **Seguimiento de los envíos de esta
   app** y pulsa **Consultar estado del intento** para obtener su última situación, cantidad
   ejecutada y precio medio. Una ejecución parcial se distingue de una ejecución completa.
6. Si quieres cancelar, hazlo en el panel Paper de Alpaca y consulta de nuevo el estado aquí.
   Usa **Actualizar cuenta** para recuperar saldos y posiciones posteriores al envío.

Son pruebas técnicas manuales y no entradas automáticas derivadas de una señal Compra. Una
orden DAY enviada después del cierre puede quedar en cola para la siguiente sesión regular;
la propuesta muestra el horario comunicado por Alpaca en zona de Ciudad de México. El precio
límite no garantiza ejecución. Una simulación no establece que la estrategia tenga una ventaja
ni reproduce precios, moneda o liquidez del SIC.

## Registro, duplicados y respuestas inciertas

Cada propuesta tiene un `client_order_id` único. Antes del POST se reclama ese intento de
forma atómica en `public.alpaca_paper_order_events`; un segundo clic o sesión que use la misma
propuesta encuentra el intento registrado y no repite el envío. La tabla separa propietario
OIDC y UUID de cuenta Paper, prohíbe cambios y borrados con la clave del servidor, y exige que
cada observación se refiera al intento del mismo propietario y cuenta. Las claves no se guardan.
En local utiliza un SQLite privado distinto; en producción reutiliza la configuración Supabase
de Seguimiento, sin cambios adicionales de Secrets. El SQL está en
[`supabase/alpaca_paper_order_events.sql`](../supabase/alpaca_paper_order_events.sql).

Los timeouts, respuestas ilegibles y duplicados del proveedor se concilian por el identificador
original mediante GET. No hay reintentos de POST. Si no se puede confirmar el resultado, el
intento permanece **Sin confirmar** y bloquea otras propuestas de la cuenta. Se puede volver
a consultar; si el estado persiste y no hay una orden en Alpaca, requiere revisión administrativa
del intento antes de permitir uno nuevo. Así un fallo no se interpreta silenciosamente como
ausencia de orden. Una observación atrasada no reduce la cantidad ejecutada ni deshace un estado
terminal ya confirmado. Los rechazos explícitos quedan cerrados y no bloquean una nueva propuesta.

Si el registro no está disponible, el envío se detiene. Si falla al guardar la respuesta después
del POST, el intento previo permanece para poder conciliarlo. El registro puede exportarse a CSV;
su lectura tiene un límite visible de 5,000 eventos por propietario y cuenta, sin truncamiento
silencioso. La consulta de estados es manual y no promete vigilancia continua de la cuenta.

La cuenta gratuita sólo proporciona datos IEX en tiempo real, que no representan el volumen
total del mercado de EE. UU. Esta conexión no utiliza ese volumen para recalcular indicadores.

La revisión local pasó 61 pruebas relacionadas con el adaptador, la interfaz, autorización,
monedas y bitácora. Se revisaron capturas con datos sintéticos a 1440, 768 y 390 px, esperando
la carga completa de Streamlit: título e importes visibles y sin desbordamiento de la página.
Se conservó la identidad SIG; la dirección de referencia fue `achromatic-ledger`, semilla
1942259728, con paleta y tipografía de la app existente. El shell se conserva para mantener
la navegación compartida. Los importes de las capturas son ejemplos locales, no datos de cuenta.

La validación local incluyó una suite completa de **584 pruebas**, pruebas focalizadas de
recuperación y revisión, Ruff y comprobación del parche. La revisión visual a 1440, 768 y 390 px
confirmó una propuesta visible, ausencia de
desbordamiento horizontal y el botón de envío deshabilitado hasta marcar la confirmación.
Se verificaron preparación sin POST, caducidad, cambio de cuenta/autorización, disponibilidad,
reclamos simultáneos, timeout con y sin aceptación, respuestas incoherentes, rechazo, ejecución
parcial y completa, observaciones atrasadas y persistencia por usuario. La tabla Supabase quedó
vacía después de una prueba transaccional revertida que verificó unicidad, relación de propietario,
RLS y permisos de sólo SELECT/INSERT. El envío efectivo a la cuenta Paper del usuario se prueba
desde la app, después de revisar y confirmar una propuesta concreta.
El asesor de seguridad no reportó hallazgos. El índice que cubre la relación entre observación
e intento permanece mientras la tabla está vacía; el aviso informativo de
[índice todavía sin uso](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index)
es esperable al crearlo antes de registrar órdenes.

Fuentes oficiales consultadas: [autenticación](https://docs.alpaca.markets/us/docs/authentication),
[cuenta](https://docs.alpaca.markets/us/reference/getaccount-1),
[posiciones](https://docs.alpaca.markets/us/reference/getallopenpositions),
[órdenes](https://docs.alpaca.markets/us/reference/getallorders-1),
[envío de órdenes](https://docs.alpaca.markets/us/reference/postorder),
[consulta por ID del cliente](https://docs.alpaca.markets/us/reference/getorderbyclientorderid),
[instrumentos](https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id),
[horario de EE. UU.](https://docs.alpaca.markets/us/reference/legacyclock),
[Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading) y
[diferencias entre IEX y SIP](https://docs.alpaca.markets/us/docs/market-data-faq).
