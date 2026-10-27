# Conexión privada con Alpaca Paper

En **Seguimiento → Alpaca Paper**, la primera entrega consulta una cuenta de simulación,
sus posiciones abiertas y hasta las 50 órdenes más recientes de todos los estados. El botón
**Conectar y consultar** comprueba las credenciales y carga la cuenta. **Actualizar cuenta**
repite la consulta. La hora UTC identifica la última respuesta completa; la pantalla no es un
monitor continuo y no envía ni cancela órdenes en esta fase.

La cuenta corresponde al mercado de origen y a importes USD. Esta vista es independiente de
la bitácora manual SIC/GBM en MXN y no cambia la fuente Yahoo/yfinance de las señales.

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

- El adaptador sólo usa GET contra `https://paper-api.alpaca.markets`, con redirecciones
  deshabilitadas. No tiene un selector de servidor live ni métodos de órdenes.
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

El envío de una orden Paper confirmada manualmente será una fase posterior, con identificación
única del intento y conciliación del estado devuelto por el intermediario. Una simulación de
ejecución no establece que la estrategia tenga una ventaja ni reproduce la liquidez SIC.

La cuenta gratuita sólo proporciona datos IEX en tiempo real, que no representan el volumen
total del mercado de EE. UU. Esta conexión no utiliza ese volumen para recalcular indicadores.

La revisión local pasó 61 pruebas relacionadas con el adaptador, la interfaz, autorización,
monedas y bitácora. Se revisaron capturas con datos sintéticos a 1440, 768 y 390 px, esperando
la carga completa de Streamlit: título e importes visibles y sin desbordamiento de la página.
Se conservó la identidad SIG; la dirección de referencia fue `achromatic-ledger`, semilla
1942259728, con paleta y tipografía de la app existente. El shell se conserva para mantener
la navegación compartida. Los importes de las capturas son ejemplos locales, no datos de cuenta.

Fuentes oficiales consultadas: [autenticación](https://docs.alpaca.markets/us/docs/authentication),
[cuenta](https://docs.alpaca.markets/us/reference/getaccount-1),
[posiciones](https://docs.alpaca.markets/us/reference/getallopenpositions),
[órdenes](https://docs.alpaca.markets/us/reference/getallorders-1),
[Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading) y
[diferencias entre IEX y SIP](https://docs.alpaca.markets/us/docs/market-data-faq).
