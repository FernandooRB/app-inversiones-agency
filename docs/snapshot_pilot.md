# Ejecución local de una cartera al corte

El módulo `snapshot_pilot.py` y el comando `scripts/run_snapshot_pilot.py` unen los importadores,
el contraste de fuentes y los motores existentes en una ejecución local reproducible. El caso
admite posiciones valuadas y cierres locales en MXN. El efectivo se conserva en la cobertura de
cuenta y queda fuera del capital optimizado y simulado.

El resultado es investigación interna bruta, retrospectiva y pendiente de revisión humana.
No reconstruye el rendimiento realizado de la cuenta, impuestos o movimientos históricos. No
requiere resolver diferencias de caja de meses anteriores para estudiar una foto de posiciones.
Tampoco autoriza una propuesta a clientes.

## Archivos necesarios

Se proporcionan ocho archivos locales. Cada uno conserva su huella SHA-256 en el resultado.

| Clave de configuración | Contenido |
| --- | --- |
| `holdings` | Cartera en `FechaCorte,Instrumento,ValorMXN`. |
| `coverage` | Resumen de cartera analizada, efectivo externo, otras partidas y total de cuenta. |
| `prices`, `reference_prices` | Dos CSV diarios de precios ajustados con `Fecha` y una columna por instrumento. |
| `rights`, `reference_rights` | Un manifiesto de derechos confirmado por producto y fuente. |
| `identity`, `reference_identity` | Un manifiesto de instrumentos por fuente; deben describir las mismas series locales en MXN. |

Las fuentes declaradas deben ser distintas. El contraste de precios usa los umbrales explícitos
del caso y detiene la ejecución cuando tiene alertas. Una coincidencia formal no acredita los
contratos, la autenticidad de identidades ni independencia económica de los proveedores.
Los contratos y originales requieren revisión humana. No generar licencias confirmadas para
hacer pasar un archivo pendiente.

La calibración utilizada requiere al menos 101 precios dentro de la ventana. Ese mínimo técnico
no demuestra suficiencia económica de la muestra. El último precio de **ambas fuentes** debe estar
dentro de la antigüedad máxima declarada, de cero a siete días naturales. Esto no sustituye un
calendario de mercado ni un control de liquidez. Las alertas heurísticas de saltos y cierres sin
cambio permanecen en los resultados y en el PDF para revisión.

## Configuración y uso

Guardar el JSON dentro de la carpeta privada del caso. Las rutas son relativas a esa carpeta;
se rechazan rutas absolutas, enlaces de archivo y rutas que salgan de ella. Un insumo aún no
recibido se declara `null`. Los supuestos completos también pueden quedar `null` mientras se definen.

```json
{
  "version": 1,
  "files": {
    "holdings": "entrada/cartera.csv",
    "coverage": "entrada/cobertura.csv",
    "prices": null,
    "rights": null,
    "identity": null,
    "reference_prices": null,
    "reference_rights": null,
    "reference_identity": null
  },
  "settings": null
}
```

Cuando estén definidos, los supuestos tienen la estructura siguiente. Los valores del ejemplo
son **sintéticos para explicar el formato**, no parámetros recomendados para una persona.

```json
{
  "history_start": "2020-01-01",
  "as_of": "2020-09-08",
  "assets": ["AAA", "BBB", "CCC"],
  "risk_free_rate": 0.02,
  "risk_free_source": "Supuesto sintético de prueba",
  "max_weight": 0.6,
  "months": 12,
  "paths": 500,
  "seed": 42,
  "rebalance_months": 12,
  "block_days": 21,
  "tolerance_pct": 0.1,
  "minimum_coverage_pct": 100.0,
  "max_price_age_days": 7
}
```

`history_start`, `as_of`, `assets`, tasa libre de riesgo, su fuente o justificación y límite
de peso son obligatorios. El resto tiene los valores por defecto indicados arriba. La tasa
se declara como fracción y los dos umbrales de contraste como porcentajes. El límite de peso
se aplica a las propuestas; la cartera existente puede superar ese límite.

Para revisar insumos sin estimar el modelo:

```powershell
.venv\Scripts\python.exe scripts/run_snapshot_pilot.py --config data/private/caso/piloto.json --output-dir data/private/caso/revision_01 --check-only
```

Para ejecutar y generar el comparativo interno:

```powershell
.venv\Scripts\python.exe scripts/run_snapshot_pilot.py --config data/private/caso/piloto.json --output-dir data/private/caso/ejecucion_01 --pdf
```

La carpeta de salida debe ser nueva. No se sobrescriben revisiones anteriores. Los resultados
contienen posiciones, pesos y cuantiles monetarios: deben permanecer en almacenamiento privado,
fuera de Git, CI y canales públicos. La consola sólo muestra estados y conteos, incluso cuando
un control rechaza importes privados.

El código de salida es `0` cuando se validaron todos los insumos o se terminó la ejecución, y
`2` cuando faltan archivos/supuestos, hay un error o ya existe la carpeta de salida. Un caso
pendiente produce sólo `readiness.json`; no se crea un resultado financiero ni un PDF. El
modo `--check-only` valida estructura y consistencia cuando todos los insumos están presentes,
pero tampoco estima el modelo.

## Qué calcula

- Cartera al corte, pesos iguales, mínima volatilidad y máximo Sharpe sobre la misma muestra.
- Contracción diagonal de covarianza calibrada con bloques cronológicos del periodo de estimación.
- VaR y CVaR históricos al 95 % para una sesión, con los motores existentes.
- Monte Carlo histórico por bloques y lognormal correlacionado para las cuatro asignaciones.
  Se conserva semilla y configuración; la aproximación usa 21 sesiones por mes.

Los escenarios son nominales brutos, sin aportaciones, retiros, honorarios, costos de operación,
reserva fiscal o ajuste por inflación. Las carteras fijas aplicadas a la muestra anterior al
corte no representan el historial real de la cuenta. Las métricas de esa muestra tampoco son
validación fuera de muestra. Perfil, costos particulares, liquidez, restricciones por clase,
benchmark de índice y validación fuera de muestra deben completarse con las herramientas
correspondientes de la aplicación antes de un análisis de mayor alcance.

Las observaciones posteriores a `as_of` se excluyen de estimación, calibración, alertas y
simulaciones. El último precio efectivo queda registrado y la fecha de las posiciones debe
coincidir con el corte solicitado. Un piloto de agosto no se presenta como cartera vigente de octubre.

## Salidas y comprobación

`analysis.json` conserva parámetros, ocho huellas de insumos, huella de configuración, fechas
efectivas, intensidad de contracción, alternativas y bandas de las ocho simulaciones. No incluye
precios crudos. `readiness.json` conserva estado, faltantes y ejecución. Con `--pdf` se añade
`comparison_internal.pdf`, usando la plantilla existente; su gráfica Monte Carlo ilustra la
asignación de mínima volatilidad por bloques. Las demás simulaciones quedan en el JSON.

`client_delivery_allowed` siempre es falso y la revisión humana permanece pendiente. Un
manifiesto de investigación interna permite un estudio interno, no se convierte en permiso de
entrega comercial por generar un PDF. La reproducción numérica exige iguales entradas,
parámetros, semilla y entorno; el PDF incluye su fecha de creación y puede variar en bytes.

Las pruebas en `tests/test_snapshot_pilot.py` usan exclusivamente datos sintéticos y cubren
ejecución conjunta, exclusión de efectivo, topes, exclusión de precios futuros, identidad,
derechos, antigüedad de ambas fuentes, entradas pendientes, confidencialidad de errores y
protección de resultados anteriores.

## Costos y comprobaciones adicionales

El comando acepta `--tariff-profile tarifas.csv`, relativo a la carpeta del JSON y con la
plantilla de perfil fechado del intermediario. Comprueba formato y vigencia incluso en
`--check-only`, si ya están definidos los supuestos. No admite una tarifa sin fechas explícitas.
La huella y las estimaciones por alternativa se añaden al resultado, y los costos aparecen en
el PDF. Debe comprobarse fuera del comando que ese perfil aplica a la cuenta y producto.
Cuando no se aporta, el costo figura pendiente; no se interpreta como cero.

`--extended-validation` añade sensibilidad de ventanas, estrés histórico, una evaluación temporal
70/30 calibrada cuando hay entrenamiento suficiente y cuatro cortes calibrados con al menos 200
retornos. La calibración de cada evaluación usa sólo su tramo de entrenamiento. No se sustituye
silenciosamente por otro estimador si falta historia; se conserva el estado insuficiente. El
benchmark de índice sigue pendiente de una serie autorizada aportada por separado.

Las validaciones adicionales y las trayectorias siguen siendo brutas. Los costos son una sección
separada, adicionales al nominal objetivo; no son ejecución autofinanciada, tarifas por orden
heterogéneas, tratamiento fiscal integral ni evidencia de negociación real. Los datos sintéticos
de las pruebas no constituyen contratos ni licencias de mercado.
