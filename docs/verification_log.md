# Guía y registro de verificación antes de entrega

Este registro acompaña cada cambio que pueda afectar un análisis, una conciliación o un reporte.
Las pruebas sintéticas verifican código; la aprobación de un caso real requiere evidencia privada,
revisión humana y los controles de la [matriz del piloto](real_data_pilot.md). Los documentos de
cuentas, importes, operaciones, identificadores, excepciones y actas de revisión no se publican.

## Mapa de funciones y comprobaciones

| Función del producto | Guía | Pruebas automatizadas | Límite actual |
| --- | --- | --- | --- |
| Recepción GBM PDF/XML y controles visibles | [Estados GBM](gbm_own_account_intake.md) | `tests/test_gbm_intake.py` | Preflight; excepciones y completitud pendientes |
| Recepción GBM CSV de movimientos | [Exportación GBM](gbm_own_account_intake.md#exportación-mensual-de-movimientos-csv) | `tests/test_gbm_export.py` | Sólo estructura; no importa ni reconcilia |
| Posiciones, efectivo y cantidades | [Cartera actual](current_holdings_import.md) | `tests/test_holdings.py`, `tests/test_cash_bridge.py`, `tests/test_position_bridge.py` | Fuente real y eventos por comprobar |
| Instrumentos, derechos y precios | [Identidad](instrument_identity.md), [fuentes](data_sources.md), [precios](price_upload.md) | `tests/test_instrument_identity.py`, `tests/test_data_rights.py`, `tests/test_price_upload.py`, `tests/test_price_source_validation.py` | Contratos y fuentes independientes pendientes |
| Markowitz, restricciones y sensibilidad | [Política](allocation_policy.md), [sensibilidad](allocation_sensitivity.md) | `tests/test_portfolio_core.py`, `tests/test_allocation_policy.py`, `tests/test_sensitivity.py` | Calibración del caso real pendiente |
| Monte Carlo, estrés y validación temporal | [Monte Carlo](monte_carlo.md), [estrés](stress_testing.md), [backtesting](backtesting.md) | `tests/test_simulation.py`, `tests/test_stress.py`, `tests/test_backtesting.py`, `tests/test_walk_forward.py` | Escenarios históricos, no predicciones garantizadas |
| Costos, impuestos y flujos | [Costos](implementation_costs.md), [tarifas](broker_tariffs.md), [flujos](tax_cash_flows.md) | `tests/test_implementation_costs.py`, `tests/test_broker_tariffs.py`, `tests/test_order_tariffs.py`, `tests/test_tax_cash_flows.py` | Contrato y revisión fiscal del caso pendientes |
| Comparativo y PDF | [Piloto](first_real_client_pilot.md) | `tests/test_reporting.py`, `tests/test_ui.py` | Documento interno; revisión final y permiso de entrega pendientes |
| Acceso, expedientes y operación | [Matriz del piloto](real_data_pilot.md) | Aún no hay prueba integral del dominio y del ciclo de expediente | No apto para datos de clientes en producción |

El importador de perfiles de costos acepta una declaración de tarifa pública, contractual o
negociada por cliente y verifica su ventana de vigencia. Esto registra el supuesto, pero no
autentica el convenio ni calcula escalones de volumen. El motor interno ya puede aplicar reglas
distintas por activo y operación, pero todavía no están conectadas a la interfaz ni al PDF.

## Regla para cada cambio

1. Registrar propósito, archivos modificados, función afectada, limitaciones y evidencia en esta
   guía o en la guía especializada. Si el hallazgo usa datos reales, dejar el detalle en
   `data/private/` y publicar sólo comportamiento y pruebas sintéticas.
2. Añadir o actualizar una prueba que compruebe el comportamiento y un caso de rechazo relevante.
   Ejecutar la prueba afectada y las comprobaciones de estilo; antes de fusionar, ejecutar la suite
   completa en los entornos de CI. Un error de datos reales no se convierte en una tolerancia
   automática para hacer pasar una prueba.
3. Repetir el ensayo local con la cuenta propia y guardar huellas de fuentes, estado, diferencias y
   resolución por fila. Confirmar que el resultado público no revele datos de la cuenta. Mantener
   abiertos los casos sin comprobante o regla de cálculo corroborada.
4. Antes de desplegar para uso con clientes, completar la matriz del piloto, probar acceso y
   eliminación/recuperación de expedientes en el entorno definitivo, revisar visualmente el PDF y
   obtener aprobación humana del caso. Publicar código o pasar CI no equivale a aprobar la entrega.

## Entrada de trabajo: exportación GBM CSV de cuenta propia

- **Cambio técnico:** validador estructural de CSV con conteos, huella SHA-256, detección de copias,
  rechazo de formatos ambiguos y salida sin datos transaccionales. No transforma el CSV en posiciones
  ni en una cartera del optimizador.
- **Evidencia de desarrollo:** `tests/test_gbm_export.py` usa operaciones inventadas; el ensayo con
  documentos propios y sus diferencias se conserva exclusivamente en `data/private/`. La revisión
  local conjunta de `test_gbm_intake.py` y `test_gbm_export.py` pasó: **59 pruebas**; `ruff check .`
  pasó. La suite completa no se pudo iniciar en este equipo porque una política local de Control de
  aplicaciones bloqueó una DLL de SciPy durante la colección. El flujo CI de Ubuntu y Windows debe
  pasar antes de integrar este cambio.
- **Estado de revisión:** pendiente de cerrar diferencias entre CSV y PDF y de comprobar completitud
  de fuentes. No habilita expedientes de clientes ni despliegue comercial.

Al cerrar este cambio, se anotarán aquí el resultado de CI y revisión.

## Entrada de trabajo: vigencia y alcance de comisiones por cliente

- **Cambio técnico:** el perfil CSV puede declarar tarifa `PUBLICA`, `CONTRACTUAL` o
  `NEGOCIADA_CLIENTE` y fechas de vigencia; una tarifa fuera de la ventana se rechaza. El formato
  anterior se mantiene como `SIN_ALCANCE` para reproducir análisis viejos, con advertencia.
- **Verificación:** pruebas sintéticas de tarifa pública frente a negociada sobre la misma orden,
  rechazo de vigencia y tipo inválidos, e integración en la interfaz. La suite local completa pasó:
  **368 pruebas**; `ruff check .` pasó. El [PR #50](https://github.com/FernandooRB/app-inversiones-agency/pull/50)
  pasó CI en Ubuntu y Windows y se fusionó por squash en `main` como `42706ce`. El árbol publicado
  coincide con el del commit local aprobado; GitHub asignó otro SHA al reconstruir los metadatos.
  No se usaron documentos reales de clientes. La rama remota del PR ya se eliminó.
- **Límite:** la clasificación y fecha son declaradas, no prueban la elegibilidad contractual.
  Un perfil de la interfaz aún aplica una sola tasa a todos los activos; quedan pendientes las
  reglas por orden en interfaz y PDF, los escalones de volumen y la verificación del acuerdo.

## Entrada de trabajo: motor interno de costos por orden

- **Cambio técnico:** `OrderCostRule` identifica activo, compra/venta, producto, mercado,
  fuente, tipo y vigencia de tarifa. El estimador usa la tasa, IVA, mínimo y costo de mercado de
  cada orden; rechaza operaciones sin regla, solapamientos, tarifas caducadas y una fuente consultada
  después de la fecha del análisis. Los costos recurrentes sólo se declaran en los supuestos
  generales. El PDF bloquea estas estimaciones hasta poder mostrar sus fuentes y tasas por orden.
- **Verificación:** `ruff check .` y **36 pruebas enfocadas** pasaron localmente. La primera
  ejecución completa bajo la sandbox registró 371 aprobadas y tres errores de preparación por
  carpetas temporales, sin fallos de aserción. El [PR #51](https://github.com/FernandooRB/app-inversiones-agency/pull/51)
  pasó la suite en CI Ubuntu y Windows y se fusionó por squash en `main` como `936e243`. Su árbol
  coincide con el del commit local aprobado `878328e`; la rama remota se eliminó.
- **Límite:** es una API interna con pruebas sintéticas. Faltan importador, interfaz, detalle en PDF,
  verificación contractual y elegibilidad por tramos de volumen. No habilita reportes para clientes.

## Entrada de trabajo: importador CSV de reglas por orden

- **Cambio técnico local:** `read_order_tariffs_csv` acepta hasta 200 reglas de compra/venta para
  activos del análisis, con esquema exacto, vigencia, fecha de consulta, fuente y cuatro cifras
  transaccionales obligatorias. Rechaza activos ajenos, reglas superpuestas, términos incompletos,
  tasas inválidas y contenido con apariencia de fórmula. El intermediario queda registrado en cada
  regla y fila de cálculo. Una orden sin cobertura continúa bloqueada por el estimador.
- **Verificación:** prueba sintética de rebalanceo con dos tasas distintas, además de casos de
  rechazo y control de PDF. La suite local completa aprobó **380 pruebas** y el código afectado pasó
  `ruff check`. No se usaron datos reales de clientes.
- **Integración:** el [PR #52](https://github.com/FernandooRB/app-inversiones-agency/pull/52)
  pasó CI en Ubuntu y Windows y se fusionó por squash en `main` como `412c1ae`. El árbol publicado
  coincide con el del commit autorizado `3d62685`; la rama remota se eliminó.
- **Límite de esa entrega:** el importador era interno; faltaban carga en la interfaz, trazabilidad
  en el PDF, verificación de convenios y elegibilidad por volumen. Una cartera agregada por símbolo
  no separa dos cuentas con tarifas distintas para el mismo instrumento.

## Entrada de trabajo: interfaz y PDF para reglas por orden

- **Cambio técnico local:** la interfaz acepta el CSV de tarifas por orden, excluye el perfil general
  y las tasas transaccionales manuales, permite costos anuales separados con fuente, y pasa las
  reglas al estimador de todas las alternativas. El detalle conserva tasa, IVA, mínimo, costo de
  mercado, fuente y vigencia por operación. Ambos PDF presentan cada orden y comprueban que sus
  cargos reconcilien con el resumen; separan los costos recurrentes y advierten que la elegibilidad
  contractual no queda acreditada.
- **Verificación:** pruebas sintéticas de integración en Streamlit, PDF individual y comparativo,
  detección de cifras alteradas; render visual de un comparativo sintético de tres páginas. La
  primera revisión visual detectó un encabezado huérfano; se corrigió y se volvió a renderizar.
  `ruff check .` pasó. La suite completa en Windows aprobó **381 pruebas** al ejecutarse fuera
  de la restricción local de carpetas temporales. Dentro de la sandbox, 378 pruebas pasaron y
  tres de GBM no pudieron preparar su `tmp_path` por `PermissionError`; no fueron fallos de
  aserción. La revisión final del diff confirmó sólo ocho archivos públicos y ningún documento
  de cuenta; el PDF sintético se volvió a renderizar y revisar tras los últimos ajustes. El
  [PR #53](https://github.com/FernandooRB/app-inversiones-agency/pull/53) pasó CI en Ubuntu y
  Windows y se fusionó por squash en `main` como `e0b6532`. Su árbol publicado coincide con el
  commit local autorizado `3fc8a24`; la rama remota se eliminó.
- **Límite:** sin convenio real comprobado ni modelado de escalones por volumen mensual. La
  agregación por símbolo sigue sin distinguir cuentas con distintas condiciones. No implica
  aprobación de asesoría personalizada, de Citi ni despliegue comercial.

## Entrada de trabajo: alcance de una cuenta

- **Decisión de producto:** preparar primero un PDF por cuenta y dejar el consolidado para después.
- **Cambio técnico local:** manifiesto de una fila con alias no identificante, intermediario,
  punto de partida, fecha de revisión y huellas completas de cartera y tarifas. La app rechaza
  reglas sin manifiesto, pesos manuales con tarifas por orden, carteras o tarifas con otra huella,
  fechas incompatibles e intermediarios mezclados. Ambos PDF muestran el alcance y advierten que
  la coincidencia de archivos no acredita pertenencia ni elegibilidad contractual.
- **Verificación local:** pruebas sintéticas de ambas modalidades (`CARTERA` y `EFECTIVO`),
  archivos sustituidos, intermediario distinto, fecha de corte y alias con apariencia de número
  de cuenta; prueba de interfaz con cartera importada y rechazo de manifiesto ausente o vacío.
  La app también rechaza perfiles y reglas de tarifas cargados pero vacíos. La suite
  local completa pasó con **385 pruebas** y `ruff check .` no encontró problemas. Un comparativo
  sintético de tres páginas se renderizó y revisó visualmente, incluido el nuevo alcance en PDF.
  La revisión final del diff confirmó diez archivos públicos y ningún documento de cuenta.
  El [PR #54](https://github.com/FernandooRB/app-inversiones-agency/pull/54) pasó CI en Ubuntu y
  Windows y se fusionó por squash en `main` como `5300b4e`. Su árbol coincide con el del commit
  autorizado `6e01886`; la rama remota se eliminó.
- **Límite:** un manifiesto declarado no detecta si una cartera ya suma varias cuentas. Falta
  relacionar cada serie GBM con su subcuenta y convenio en el expediente privado; el consolidado
  y los tramos de volumen no se calculan.

## Auditoría de preparación para datos reales — 29 de septiembre de 2026

- [Dictamen técnico](audit_2026-09-29.md): el producto sigue siendo investigación interna; no se
  aprobó la entrega individualizada a clientes. Se creó un expediente privado neutro para el
  piloto GBM BMV y un inventario de documentos sin publicar identificadores.
- El cambio local de logging evita registrar mensajes y traceback de excepciones inesperadas;
  la prueba dirigida de privacidad y las pruebas de interfaz pasaron (**13 pruebas**). `ruff check .`
  compilación Python y `pip check` pasaron. La suite completa aprobó **386 pruebas** fuera de la
  restricción local de carpetas temporales. Dentro de la sandbox aprobaron 383 y tres pruebas GBM
  no pudieron preparar `tmp_path` por `WinError 5`; no llegaron a ejecutar aserciones. El
  [PR #55](https://github.com/FernandooRB/app-inversiones-agency/pull/55) pasó CI en Ubuntu y Windows.
- El control por cuenta de `6e01886` ya está integrado mediante el PR #54. Los cambios de esta
  auditoría y del logging pasaron la suite local completa y CI remoto para el PR #55.
- Una revisión ampliada del inventario GBM detectó 18 CFDI estructurales entre 22 XML distintos,
  todos con aritmética interna exacta; cuatro XML requieren clasificación. Diecisiete CFDI tienen
  referencia textual candidata a una serie y uno no. Las 30 compraventas visibles con cargos
  presentan 26 netos exactos y cuatro diferencias de un centavo, todavía abiertas. La serie BMV
  quedó vinculada documentalmente por un estado entregado desde esa cartera; no se ha aprobado
  su convenio ni la conciliación financiera.

## Preflight local de cartera XLSX GBM — 29 de septiembre de 2026

- Se añadió un [lector estructural](../scripts/inspect_gbm_portfolio_xlsx.py) del diseño observado
  de una hoja de cartera. Rechaza fórmulas, etiquetas duplicadas, estructura desconocida y ZIP
  con contenido descomprimido excesivo. Sólo devuelve huella y conteos. No importa movimientos
  ni asigna fecha o contrato.
- Se ejecutó contra una exportación privada propia: reconoció tres renglones de posiciones y
  cuatro de efectivo, sin imprimir símbolos ni importes. El cotejo con el estado de agosto se
  conserva únicamente en el expediente privado; ninguna valuación del XLSX se aceptó para el
  corte por coincidencia de carpeta.
- Seis pruebas sintéticas dirigidas pasaron. La suite completa terminó con **392 pruebas**;
  `ruff check .`, `pip check` y `git diff --check` pasaron. En una ejecución previa Windows
  imprimió una violación de acceso nativa al iniciar una prueba de Streamlit; la interfaz
  aislada aprobó 12 pruebas, el resto 380 y la repetición completa terminó sin esa señal.
  El [PR #56](https://github.com/FernandooRB/app-inversiones-agency/pull/56) pasó CI en Ubuntu y
  Windows y se integró por squash en `main` como `bfcc1ba`; su rama remota se eliminó.

## Aclaración de fuentes y costos GBM — 30 de septiembre de 2026

- El titular confirmó que no puede descargar el historial de movimientos de su cartera BMV.
  La ruta documentada usa los estados PDF como fuente principal, con procedencia por fila,
  revisión independiente y excepciones abiertas; el XLSX sigue siendo sólo una foto.
- Confirmó como referencia general la tabla de la ayuda GBM, coincidente con su FAQ pública.
  Los 22 cargos históricos visibles de la serie BMV corresponden a 0.25 % al centavo. Se
  conserva la diferencia entre tasa observada para el ensayo propio, tabla pública por
  producto y posibles condiciones particulares de clientes futuros. No se automatiza el
  tramo de tres meses ni se recalculan cargos históricos para sustituir el estado.
- En el expediente privado se generó un libro de efectivo desde los dos PDF consecutivos:
  45 filas con procedencia (dos aperturas y 43 movimientos). Reproduce el preflight:
  32 transiciones exactas, 11 con un centavo y tres desfases de día. Se inspeccionó visualmente
  una página de movimientos de cada PDF; el resto y el puente de títulos requieren revisión.
  El libro conserva `REVIEW_REQUIRED` y no se publica con los documentos.
- Esta aclaración modifica guías, no código. Se revisaron enlaces, alcance y ausencia de
  identificadores privados en el cambio público; la conciliación financiera sigue abierta.
