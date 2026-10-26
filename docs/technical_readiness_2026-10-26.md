# Revisión de Seguimiento y preparación de una prueba en SIC · 26 de octubre de 2026

## Alcance y resultado

La estrategia `tendencias-confirmadas-v1` es una regla de investigación, no un sistema de
ejecución. Esta revisión amplió el contraste de datos, reprodujo las reglas en tres periodos
consecutivos por símbolo y preparó un borrador manual para operar en SIC con GBM. Ninguna orden
se creó ni se envió. El resultado **no justifica tomar una señal como recomendación suficiente
para invertir dinero real**: hubo pocas operaciones y la estrategia quedó por debajo de comprar
y mantener en 17 de 18 comparaciones símbolo-periodo. Comprar y mantener también es una
simulación por precio en el mercado de origen, no una alternativa SIC ejecutable en MXN.

## Calidad de datos

`scripts/audit_market_sources.py` descarga por separado la serie de la app (Yahoo/yfinance) y el
histórico público de Nasdaq. El segundo es sólo una fuente de contraste manual; su respuesta
JSON no tiene garantía de estabilidad ni entra en producción. La auditoría exige 504 sesiones
comunes recientes y compara nueve condiciones de la estrategia y la señal final, además de
fechas, cierres, volúmenes y eventos corporativos. El reporte completo se guarda en
`data/private/market_source_audit.json`, fuera de Git.

| Símbolo | Sesiones comunes | Diferencias de condiciones / señales | Máxima diferencia de volumen diario |
|---|---:|---:|---:|
| AAPL | 504 | 0 / 0 | 0.224 % |
| MSFT | 504 | 0 / 0 | 0.273 % |
| NVDA | 504 | 0 / 0 | 1.001 % |
| KO | 504 | 0 / 0 | 0.107 % |
| QQQ | 504 | 0 / 0 | 1.188 % |
| SPY | No evaluable | No se comparó | Nasdaq informó volumen `N/A` el 20-04-2026 |

La ausencia de volumen de SPY ocurrió en la fuente independiente de Nasdaq; no se sustituyó ni
se eliminó silenciosamente. La auditoría separa los errores por símbolo. El precio, volumen y
dividendos del mercado de origen **no** prueban la liquidez ni el precio de la serie SIC.

## Robustez retrospectiva

`scripts/validate_technical_periods.py` tomó cinco años de Yahoo por símbolo y aplicó el motor
de señales existente en tres bloques no superpuestos de 252 sesiones, con 252 sesiones previas
de calentamiento. Cada bloque se truncó a su fecha final para impedir que una señal pasada vea
barras futuras. Se mantuvieron los costos base de 0.25 % más 10 puntos básicos por lado y se
repitió la estrategia con 0.50 % más 20 puntos básicos por lado. No hubo ajuste de parámetros
por bloque; tampoco hubo prueba prospectiva ni ejecución real. El reporte queda en
`data/private/technical_period_validation.json`, fuera de Git.

| Símbolo | Operaciones en los tres bloques | Bloques en que la estrategia neta superó comprar y mantener neto |
|---|---:|---:|
| AAPL | 3 | 0 de 3 |
| MSFT | 3 | 1 de 3 |
| NVDA | 2 | 0 de 3 |
| KO | 3 | 0 de 3 |
| SPY | 1 | 0 de 3 |
| QQQ | 0 | 0 de 3 |

Son 12 operaciones entre seis instrumentos y tres bloques, demasiado pocas para inferir una
ventaja fiable. La pantalla ahora permite repetir esta comprobación por ticker con costos base y
de estrés y exportar la tabla CSV; la curva comparativa pertenece a la prueba histórica de dos
años. Los periodos retrospectivos no son validación fuera de muestra
prospectiva. [Investor.gov advierte](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)
que el rendimiento pasado e hipotético no predice el futuro y que costos y circunstancias del
inversionista importan.

## Respaldo y seguridad de listas

La tabla Supabase conservaba una fila al corte. Se generó una copia administrativa de esa fila
en `data/private/supabase_watchlists_backup_2026-10-26.json`, ignorada por Git, y se verificó
que el JSON contiene una lista. La copia es **local** y de un solo corte; todavía requiere
trasladarse a almacenamiento externo seguro para sobrevivir a la pérdida del equipo. La app
permite descargar un JSON de la lista del usuario autenticado y restaurarlo sobre **su propia**
lista con confirmación explícita. Ese archivo no contiene hash de propietario, OIDC ni claves.
La importación verifica versión, tamaño, fecha y hasta 25 tickers normalizados. El test de
restauración usa dos usuarios y comprueba que el segundo queda intacto.

El proyecto Supabase mantiene RLS habilitado y la tabla no concede acceso a `anon` ni
`authenticated`; la clave `sb_secret_` vive sólo en los Secrets del servidor. La revisión de
advisors de seguridad y rendimiento no mostró avisos al corte. El plan gratuito
[no incluye respaldos diarios automáticos](https://supabase.com/docs/guides/platform/backups);
Supabase recomienda exportaciones periódicas fuera de la plataforma. La exportación manual
por usuario y esta copia puntual **no equivalen** a una política automática con retención y
prueba de restauración del proyecto completo.

## SIC y GBM

La sección **Preparar prueba en SIC · GBM** exige una señal Compra para habilitar el borrador.
Solicita serie e ISIN locales, bid/ask, volumen y hora recientes de GBM, stop y objetivo en MXN,
capital máximo, pérdida máxima planeada y costo por lado. Calcula títulos enteros bajo los
límites de capital y pérdida planeada, usando el ask local como precio de entrada. Si no caben
títulos o el objetivo no cubre costos, rechaza el borrador. No convierte el ATR ni los niveles
USD a MXN mediante un tipo de cambio implícito. Un salto de precio, spread cambiante o falta de
liquidez puede causar una pérdida mayor que la planeada.

La alternativa **Conectar bróker** aparece en la pantalla, pero no habilita envío de órdenes.
No se ha verificado una API de negociación para la cuenta GBM del usuario, sus permisos ni un
entorno de pruebas. [La información pública de Open Banking de GBM](https://gbm.com/open-banking/)
no documenta, por sí sola, una API para órdenes minoristas. Los [tipos de órdenes de Trading MX](https://gbm.com/faqs/que-tipos-de-ordenes-existen-en-trading-mx)
deben verificarse en la cuenta y serie concretas antes de operar.

Antes de una prueba con dinero real faltan: elegir capital y pérdida máxima aceptable; una
serie SIC y cotización actual verificadas en GBM; comisiones reales; revisión de la posición
existente, exposición agregada y horario; una validación prospectiva en papel suficientemente
informativa; y aprobación explícita de una propuesta concreta. La app no tiene datos locales
SIC licenciados ni conexión de órdenes. No puede confirmar una ejecución ni un stop garantizado.

## Reproducción

```powershell
.venv\Scripts\python.exe scripts/audit_market_sources.py
.venv\Scripts\python.exe scripts/validate_technical_periods.py
$env:TEMP='D:\OptimizacionPortafolio\tmp\private'; $env:TMP=$env:TEMP
.venv\Scripts\python.exe -m pytest -q --basetemp=tmp/private/pytest_readiness
```

Las dos auditorías consultan proveedores externos y pueden cambiar al revisarse datos o
metadatos. `data/private` y `tmp/private` se excluyen de Git.
