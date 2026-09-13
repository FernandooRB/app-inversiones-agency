# Optimizador de Portafolios V2

Aplicación educativa en Streamlit para analizar asignaciones de activos con datos históricos. Calcula
portafolios de máximo Sharpe y mínima volatilidad, una frontera eficiente, VaR, CVaR y un reporte PDF.

> **Importante:** los resultados son estimaciones históricas y no constituyen asesoría, una recomendación
> personalizada ni una garantía de rendimiento futuro.

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

Requiere Python 3.11 o superior.

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

- Yahoo Finance no debe asumirse como fuente contractual para un servicio de inversión en producción.
- No hay conversión de monedas; los activos deben analizarse en una base comparable.
- No se incorporan costos, impuestos, spreads, liquidez ni restricciones regulatorias.
- La media histórica no es un pronóstico.
- No existe gestión de clientes, autenticación ni persistencia de información personal.
- Antes de un uso comercial deben revisarse licenciamiento de datos, privacidad y cumplimiento aplicable.

## Estructura

```text
app_inversiones.py   Interfaz Streamlit
portfolio_core.py    Datos, métricas, optimización y riesgo
reporting.py         Reporte PDF
tests/               Pruebas unitarias
```

## Próximas fases

- Backtesting fuera de muestra y benchmarks.
- Covarianza robusta y Black-Litterman.
- Perfiles IR1–IR5 y restricciones por clase de activo.
- Conversión de moneda y riesgo cambiario.
- Costos, impuestos y rebalanceo.
- Autenticación, expediente de cliente y audit trail.

## Licencia

No se ha definido una licencia. Conserva el repositorio privado o añade una licencia apropiada antes de
autorizar reutilización por terceros.
