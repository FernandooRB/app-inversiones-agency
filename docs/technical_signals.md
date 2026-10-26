# Seguimiento y señales

Pantalla interna SIG para investigación de acciones con horizonte de días a semanas. La estrategia
`tendencias-confirmadas-v1` presenta Compra, Esperar, Venta / revisar reducción o No evaluable.
Una señal de venta corresponde a revisar una posición larga existente. Las decisiones y operaciones
son manuales; los porcentajes de operaciones ganadoras describen la muestra simulada.

## Uso y almacenamiento

En **Seguimiento**, añade o elimina tickers separados por comas y pulsa **Guardar lista**. Se
normalizan a mayúsculas, se eliminan duplicados y se admiten hasta 25. **Copiar desde Análisis**
lleva sus tickers al editor, para revisarlos antes de guardar. Una lista vacía permite borrar el
seguimiento. **Actualizar señales** consulta los símbolos guardados; seleccionar una fila o el
selector de acción abre el detalle. El filtro se aplica a las señales de la consulta actual.

En local, el archivo SQLite predeterminado es `data/private/technical_watchlists.db`, excluido de
Git. Su ubicación puede configurarse con `[technical_watchlist].database_path` en los secretos de
Streamlit y debe ser absoluta. En Streamlit Community Cloud este archivo **no es persistente**.
Para conservar la lista, crear un proyecto Supabase y ejecutar
[`supabase/technical_watchlists.sql`](../supabase/technical_watchlists.sql) en su SQL Editor.
Después, en **Settings > Secrets** de la app de Streamlit Cloud, añadir sin borrar los secretos OIDC:

```toml
[technical_watchlist]
backend = "supabase"
url = "https://TU_PROJECT_REF.supabase.co"
secret_key = "sb_secret_TU_CLAVE_REAL"
```

Obtener la URL del proyecto y una clave **secret** `sb_secret_` en Supabase Settings > API Keys.
Escribir la clave sólo en los secretos del servidor, nunca en Git, el navegador o el chat.
El backend usa la API REST de Supabase con HTTPS y no incorpora Supabase Auth: mantiene la
autorización Google OIDC de la app. El acceso a la tabla con clave secret omite RLS, por lo que
el servidor verifica la identidad antes de calcular la clave del usuario y consultar su fila.
La tabla no concede acceso a `anon` ni a `authenticated`.

El primer acceso a Supabase intenta copiar la lista del usuario desde el SQLite local si todavía
existe; una fila remota vacía no vuelve a importar datos antiguos. Como Community Cloud puede
haber eliminado el archivo antes de ese momento, conviene comprobar las listas y volver a añadir
los tickers faltantes. Un error de Supabase se muestra sin guardar silenciosamente en SQLite.
El plan gratuito puede pausar proyectos por baja actividad y no incluye copias automáticas;
programar exportaciones periódicas de la tabla. Esta migración **no** cambia la persistencia de
Expedientes, que usa un SQLite distinto.

Las listas guardan únicamente tickers y fecha de actualización, asociados al hash de la pareja
OIDC issuer/subject verificada. No se identifica al usuario por correo. El acceso requiere la
autorización OIDC existente en cada ejecución.
Los datos de mercado cacheados son públicos; la lista y los resultados de sesión son propios
del usuario. El cambio de identidad elimina el estado de seguimiento anterior.

## Fuente y disponibilidad

Se solicitan cinco años de OHLCV diarios con `yfinance.Ticker.history`, `auto_adjust=False`,
`back_adjust=False`, `repair=False` y eventos corporativos. La caché dura una hora;
la actualización manual fuerza consultas nuevas sin vaciar otras cachés de la app. La caché
de mercado admite como máximo 50 entradas para limitar memoria. Yahoo/yfinance conserva el alcance de
investigación interna establecido en la [matriz de fuentes](data_sources.md).

Los cálculos usan Open, High, Low y Close, respetando los ajustes de splits que ya incorpora el
proveedor. Adj Close se conserva separado y no entra en el cálculo. Se muestran moneda, mercado,
zona horaria, fuente, hora de consulta y sesión evaluada. El volumen del mercado de origen no
describe la liquidez local del SIC; los precios se muestran en la unidad de cotización original,
sin conversión FX. Los eventos de dividendos y splits pueden revisarse en el detalle.

La vela de hoy sólo entra si los metadatos identifican el fin de la sesión regular de ese mismo
día, en la zona de la bolsa, y la consulta se realizó al menos 15 minutos después del cierre.
Una vela descargada antes del cierre sigue excluida aunque se revise después; hay que actualizar.
Si falta ese horario, se excluye hoy. Fechas futuras y velas en curso quedan fuera. Se requieren 252 sesiones válidas,
precios positivos y finitos, volumen positivo en todas las observaciones y velas coherentes.
No se rellenan huecos ni se eliminan observaciones defectuosas silenciosamente. Una última sesión
de más de cinco días naturales, moneda/mercado/zona ausentes o un fallo del proveedor produce
No evaluable con su motivo. Un ticker fallido no impide consultar el resto.

## Indicadores y reglas

- Medias simples de cierre de 20, 50 y 200 sesiones.
- Volumen relativo: volumen de la sesión / promedio de las 20 sesiones anteriores.
- RSI 14 de Wilder: semilla de 14 cambios y recurrencia de Wilder. RSI 100 si sólo hay ganancias,
  0 si sólo hay pérdidas y 50 si no hay cambios.
- ATR 14 de Wilder: true range incluye gaps, con semilla media de 14 rangos.
- MACD: EMA 12 menos EMA 26; señal EMA 9; histograma MACD menos señal. EMA recursiva
  `adjust=False`, mostrando resultados tras completar su calentamiento.
- Soporte y resistencia: mínimo Low y máximo High de las 20 sesiones anteriores.

**Compra** exige todas estas condiciones: cierre por encima de resistencia; cierre > media 50 >
media 200; volumen relativo ≥ 1.5; RSI entre 50 y 70 inclusive y superior al anterior; histograma
MACD > 0. **Venta / revisar reducción** exige cierre por debajo del soporte, volumen relativo
≥ 1.5, RSI < 45 e histograma MACD < 0. Las demás combinaciones son **Esperar**. Cada condición
se presenta como Cumple o Pendiente con la lectura observada. No hay puntaje de confianza.
En **Esperar**, la conclusión enumera por separado las condiciones que faltan para compra y para
venta. La lectura de volumen muestra títulos, promedio de las 20 sesiones previas y cociente para
que la razón sea comprobable. Los datos ausentes aparecen como guiones en la tabla sin convertirse
en ceros ni en texto numérico.

En Compra, el plan toma como entrada inicial el último cierre: stop = entrada − 2 ATR y objetivo =
entrada + 4 ATR. Cambiar la entrada recalcula ambos. Se exige ATR positivo y stop positivo.
Se muestra la relación bruta 2:1 y la relación tras costos y deslizamiento supuestos.
Si alcanzar el objetivo no deja beneficio neto bajo esos supuestos, se muestra una advertencia.

## Simulación reproducible

Se calcula bajo demanda por acción para los últimos dos años hasta la última sesión disponible.
Se exigen 252 observaciones anteriores al inicio de esa ventana, para que la señal previa a la
primera apertura ya sea evaluable. Esto supera el mínimo inicial de 200 para las medias y evita
tratar sesiones sin calentamiento como días sin oportunidades. No se sustituye por una ventana
parcial. El motor de señales es el mismo del detalle; cada señal requiere sus 252 sesiones.

- Capital inicial relativo 100, posiciones largas, una a la vez, acciones fraccionarias simuladas.
- Señal al cierre t, entrada o salida técnica en la apertura t+1. Sin reinversión dentro del mismo
  día tras una salida. La primera apertura puede usar la señal de la sesión inmediatamente
  anterior a la ventana; todas las ejecuciones caen dentro de la evaluación.
- Stop y objetivo fijos desde la apertura de entrada, con ATR de la sesión de la señal.
- Gaps que superan un nivel salen en la apertura. Dentro de una vela que toca ambos niveles,
  primero se ejecuta el stop. El deslizamiento se aplica a cada ejecución.
- Tras 20 sesiones de tenencia, salida en la apertura siguiente. Una posición restante se
  liquida al último cierre de evaluación, identificada en el registro.
- Costo por lado 0.25 % y deslizamiento por lado 10 pb por defecto. Son editables y no proceden
  de un tarifario. La entrada paga `precio × (1 + deslizamiento) × (1 + costo)`; la salida recibe
  `precio × (1 − deslizamiento) × (1 − costo)`. Son los mismos supuestos para comprar y mantener.

La curva bruta sigue los mismos tiempos y precios de referencia que la neta, sin costos ni
deslizamiento. Comprar y mantener entra en la primera apertura y sale en el último cierre de la
misma evaluación. Las curvas netas marcan posiciones abiertas a cierre y descuentan el costo de
salida cuando ésta ocurre. La máxima caída incluye el capital inicial anterior a la primera
compra. La proporción ganadora cuenta operaciones cerradas con retorno neto positivo; sin
operaciones se muestra como no aplicable. La evaluación es de rendimiento por precio: dividendos,
intereses del efectivo e impuestos están fuera del cálculo. Los gráficos de capital y el registro
de operaciones pueden descargarse como CSV para revisión interna.

## Verificación

Pruebas unitarias para fórmulas, umbrales, calentamiento, volumen, ajustes, metadatos, cierre de
sesión y ausencia de anticipación; pruebas de ejecución para gaps, stops simultáneos, costos,
plazo máximo y liquidación; SQLite para persistencia, validación y aislamiento de identidades;
AppTest para navegación, edición, actualización, filtros, selección y simulación.

La vista previa local `scripts/preview_technical.py` utiliza exclusivamente series e identidades
sintéticas, escucha en localhost y permite revisar escritorio, tableta y móvil. No modifica el
acceso del punto de entrada de producción. Únicamente SIM-ALFA y SIM-BETA tienen precios de ejemplo;
SIM-ALFA muestra Compra y SIM-BETA muestra Esperar con volumen insuficiente. Los tickers reales no
reciben cotizaciones ficticias. Conserva su lista al recargar, incluso vacía, y sólo muestra la
navegación disponible en la demostración.

### Verificación local

El [informe de auditoría del 23 de octubre de 2026](audit_2026-10-23.md) registra las comprobaciones,
correcciones y limitaciones. La tabla mantiene cifras numéricas para ordenar por valor; un dato
ausente conserva su valor nulo y nunca se convierte en cero para simular una cotización.

La consulta real de AAPL devolvió 1255 observaciones y metadatos de NasdaqGS/USD, pero el
proveedor entregó el cierre de 2026-10-23 como ausente. El control lo clasificó como No evaluable;
no se sustituyó por otro campo ni se inventó una señal. La interfaz identifica campo y fecha
de los datos inválidos para permitir una revisión o actualización posterior.

### Comprobación de la app pública · 25 de octubre de 2026 (Ciudad de México)

Tras guardar AAPL en Supabase, el usuario confirmó que la lista permaneció al recargar. Al pulsar
**Actualizar señales**, la app evaluó la sesión del 23 de octubre: cierre USD 347.73, cambio diario
−0.14 %, volumen relativo 1.04×, RSI 63.92 y señal **Esperar**. El volumen no alcanza el umbral
1.5× de Compra, independientemente de las demás condiciones. El cierre USD 347.73 coincide con los
datos publicados por [Yahoo Finance](https://finance.yahoo.com/quote/AAPL/history/) y por el
[reporte de Nasdaq Dorsey Wright del 23 de octubre](https://dorseywright.nasdaq.com/reports/database/menu/stocktype/1/date/2026-10-23/new_all//rpt/56/allprice/1/all_scales/1/sourcerpt/).

### Conciliación posterior de AAPL · 25 de octubre de 2026 (Ciudad de México)

Se descargaron las barras diarias de Yahoo mediante el adaptador de la app (cinco años, 1255
sesiones) y las del [histórico público de Nasdaq](https://www.nasdaq.com/market-activity/stocks/aapl/historical)
(desde octubre de 2021, 1271 sesiones). La consulta de Nasdaq utilizó su
[respuesta JSON pública](https://api.nasdaq.com/api/quote/AAPL/historical?assetclass=stocks&fromdate=2021-10-01&todate=2026-10-23&limit=2000),
que puede cambiar de disponibilidad o formato; **no** es una dependencia de producción. Se
normalizaron las fechas a la sesión de Nueva York, se ordenaron las barras y se compararon
las 502 sesiones comunes del 23 de octubre de 2024 al 23 de octubre de 2026. Ambas series
terminaban el 23 de octubre. Los cálculos se hicieron con las reglas de la app y, para la última
sesión, con implementaciones separadas de la media de 20 volúmenes anteriores, la recurrencia RSI
de Wilder y las EMA recursivas del MACD.

| AAPL, sesión 2026-10-23 | Yahoo/yfinance | Nasdaq |
|---|---:|---:|
| Cierre | USD 347.7300 | USD 347.7250 |
| Volumen de la sesión | 39,496,500 | 39,539,690 |
| Media de las 20 sesiones anteriores | 38,034,150 | 38,034,146 |
| Volumen relativo | 1.03845× | 1.03958× |
| RSI 14 | 63.9185 | 63.9101 |
| Histograma MACD | 0.31621 | 0.31589 |
| Señal | Esperar | Esperar |

Las fórmulas separadas reprodujeron los tres indicadores de la app a precisión numérica. En esa
sesión sólo se cumplieron la condición de tendencia y el histograma MACD positivo para Compra;
ninguna condición de Venta se cumplió. El volumen de Nasdaq fue 0.109 % mayor que el de Yahoo,
pero ambos quedaron lejos del umbral de 1.5×. En las 502 sesiones comunes no hubo diferencias en
ninguna de las nueve condiciones evaluadas ni en las señales finales: ambas series produjeron tres
sesiones de Compra y diez de Venta / revisar reducción. La mayor diferencia de cierre fue USD
0.00501 y la mayor diferencia relativa de volumen diario, 0.224 %.

Este cotejo respalda **las reglas y la señal de AAPL en el periodo revisado**; no garantiza que
otros símbolos o futuras revisiones de los proveedores coincidan. Tampoco valida el rendimiento
futuro ni reemplaza la revisión del precio y la liquidez de la plaza donde se operaría.
