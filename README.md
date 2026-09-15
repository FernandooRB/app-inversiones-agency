# Optimizador de Portafolios V2

Aplicación educativa de uso interno en Streamlit para analizar asignaciones de activos con datos históricos. Calcula
portafolios de máximo Sharpe y mínima volatilidad, una frontera eficiente, VaR, CVaR y un reporte PDF.
Incluye [escenarios Monte Carlo](docs/monte_carlo.md) para investigación interna,
con métodos histórico por bloques y lognormal correlacionado, y
[pruebas de estrés](docs/stress_testing.md) históricas e hipotéticas. El
[catálogo piloto México/SIC](docs/instrument_catalog.md) distingue el instrumento negociable de
la serie utilizada por el motor y bloquea bonos, efectivo y fondos hasta contar con su valoración.
El [preparador de CETES](docs/cetes_adapter.md) convierte archivos de precio y plazo en un índice
revisable que puede añadirse al optimizador mixto en MXN.
La [validación fuera de muestra](docs/backtesting.md) compara Markowitz, pesos iguales y una
cartera actual opcional, tanto con asignación fija como con revisiones de 3, 6 o 12 meses
y costos supuestos.
La [sensibilidad de asignaciones](docs/allocation_sensitivity.md) reestima los pesos con
ventanas históricas de 60, 126 y 252 retornos para mostrar cuánto dependen de la muestra.

> **Importante:** los resultados son estimaciones históricas y no constituyen asesoría, una recomendación
> personalizada ni una garantía de rendimiento futuro.

El PDF compara escenarios matemáticos. La aplicación no está habilitada como flujo de
recomendaciones individualizadas para clientes ni como sistema de ejecución de operaciones.
Ese uso requiere definir antes su encuadre regulatorio, los permisos laborales aplicables,
los derechos de datos y la revisión de cada entregable.

## Cambios de seguridad y metodología en V2

- Precios ajustados explícitamente por el proveedor; se eliminó el ajuste manual incorrecto.
- Rendimientos aritméticos consistentes para agregación de portafolio.
- Diferencia clara entre portafolios aleatorios y frontera eficiente optimizada.
- Tasa libre de riesgo, límite de concentración, confianza y horizonte configurables.
- VaR y CVaR expresados como magnitudes positivas de pérdida y también como importe.
- Validación de tickers, fechas, observaciones mínimas y factibilidad de restricciones.
- Errores internos registrados en el servidor, sin mostrar trazas al usuario.
- CORS y protección XSRF activados.
- Núcleo financiero separado de la interfaz y cubierto por pruebas.
- Flujo de CI de solo lectura con permisos mínimos.

## Instalación

Entorno soportado y probado: Python 3.12. Las instalaciones utilizan las versiones
exactas de `constraints-tested.txt`, incluidas las dependencias transitivas del entorno probado.
CI comprueba instalación, integridad de dependencias y pruebas en Linux y Windows.
El archivo de restricciones fija versiones; no es un bloqueo criptográfico por hashes.

```bash
python -m venv .venv
```

En Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app_inversiones.py
```

En Linux o macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app_inversiones.py
```

## Pruebas y calidad

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest
```

## Metodología

1. Se descargan precios de cierre ajustados mediante `yfinance` con `auto_adjust=True`.
2. Se alinean las fechas y se requieren al menos 60 observaciones comunes.
3. Se calculan rendimientos aritméticos diarios.
4. La media y covarianza se anualizan usando 252 sesiones.
5. SLSQP resuelve los portafolios long-only bajo un peso máximo por activo.
6. La frontera eficiente minimiza varianza para una secuencia de retornos objetivo factibles.
7. VaR paramétrico utiliza media y volatilidad; VaR y CVaR históricos usan la cola observada.

## Limitaciones actuales

- VaR histórico multidiario capitaliza retornos de una cartera rebalanceada diariamente;
  las ventanas se solapan. El VaR normal sigue siendo una aproximación aditiva con retornos independientes.
- La nube aleatoria respeta el límite por activo mediante contracción hacia pesos iguales;
  no es una muestra uniforme ni una simulación de precios futuros.
- Las pruebas automatizadas no son una auditoría de seguridad ni validación para operar con clientes.

- Yahoo Finance no debe asumirse como fuente contractual para un servicio de inversión en producción.
- Las monedas se declaran explícitamente; no hay detección automática de unidades.
- Las simulaciones y pruebas de rebalanceo aceptan costos supuestos en puntos base; la
  optimización principal y el PDF no descuentan tarifarios reales, impuestos, spreads ni liquidez.
- La media histórica no es un pronóstico.
- No existe gestión de clientes ni persistencia de información personal.
- Antes de un uso comercial deben revisarse licenciamiento de datos, privacidad y cumplimiento aplicable.

## Estructura

```text
app_inversiones.py   Interfaz Streamlit
portfolio_core.py    Datos, métricas, optimización y riesgo
instruments.py       Catálogo y reglas de integración por tipo de instrumento
fixed_income.py       Valuación y preparación de series de CETES
backtesting.py         Evaluación hipotética con fecha de corte
walk_forward.py        Evaluación con revisiones sucesivas
sensitivity.py         Diagnóstico de estabilidad de pesos
reporting.py         Reporte PDF
tests/               Pruebas unitarias
```

## Próximas fases

- Covarianza robusta y Black-Litterman.
- Perfiles IR1–IR5 y restricciones por clase de activo.
- Cobertura cambiaria y validación de metadatos de instrumentos.
- Costos, impuestos y rebalanceo.
- Expediente de cliente y audit trail.

## Licencia

No se ha definido una licencia. Conserva el repositorio privado o añade una licencia apropiada antes de
autorizar reutilización por terceros.

## Acceso OIDC (obligatorio)

La aplicación deniega acceso si no hay configuración. Copia `.streamlit/secrets.example.toml`
a `.streamlit/secrets.toml` únicamente en el servidor y configura una aplicación OIDC.
El ejemplo utiliza Google. Registra la URL exacta `/oauth2callback` del despliegue con HTTPS
(localhost HTTP se reserva para desarrollo), y genera `cookie_secret` con
`python -c "import secrets; print(secrets.token_urlsafe(64))"`.
Guarda client_secret y cookie_secret en los secretos del alojamiento; nunca en Git ni en conversaciones.
Añade cada usuario permitido con su `issuer` y `subject` verificados en el proveedor.
No se autoriza por email ni existe registro abierto. Se comprueba `exp` en cada ejecución;
las interacciones vuelven a comprobarlo. Cerrar sesión borra el estado local de Streamlit.
La pantalla ya abierta no se borra automáticamente al expirar el token hasta la siguiente interacción.
La sesión del proveedor se administra por separado. La configuración OIDC real requiere una prueba
manual de login, rechazo de un segundo usuario y logout en el dominio definitivo.
Referencia: https://docs.streamlit.io/develop/api-reference/user/st.login

## Multimoneda

Declara una moneda de cotización por ticker, en el mismo orden de los tickers únicos.
Se admiten USD, MXN, EUR, GBP, CAD, JPY y CHF. La moneda es una declaración del usuario:
no se verifica automáticamente con los metadatos del instrumento. No uses títulos cotizados en
peniques u otras subunidades. Comprueba las unidades con la fuente antes de analizar.
Cada precio se multiplica por el FX diario `COTIZACIONBASE=X`; no se rellenan fechas ausentes.
Se necesitan al menos 60 precios comunes después de la conversión. La alineación es por fecha,
no por hora de cierre; mercados con cierres distintos pueden introducir sesgo.
La tasa libre de riesgo y el capital deben expresarse en la moneda base.
El PDF incluye moneda, asignación, importes, VaR paramétrico e histórico, parámetros y paginación.

## Validación con datos reales

Ejecuta `python scripts/validate_live.py > live-validation.json` para comprobar AAPL y MSFT
convertidos de USD a MXN en enero-junio de 2024. Código 0: integración completada;
código 2: datos no disponibles. Errores inesperados producen un fallo, nunca un aprobado.
El JSON registra fecha, fuente, periodo, observaciones, pesos y huella de los precios si tiene éxito.
Es una prueba de integración, no un contraste independiente de exactitud financiera ni un backtest.
El intento del 14 de septiembre de 2026 quedó bloqueado: Yahoo devolvió rate limiting y un error
local de caché. No hay todavía validación satisfactoria con datos reales.
