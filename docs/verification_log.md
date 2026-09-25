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
| Costos, impuestos y flujos | [Costos](implementation_costs.md), [tarifas](broker_tariffs.md), [flujos](tax_cash_flows.md) | `tests/test_implementation_costs.py`, `tests/test_broker_tariffs.py`, `tests/test_tax_cash_flows.py` | Contrato y revisión fiscal del caso pendientes |
| Comparativo y PDF | [Piloto](first_real_client_pilot.md) | `tests/test_reporting.py`, `tests/test_ui.py` | Documento interno; revisión final y permiso de entrega pendientes |
| Acceso, expedientes y operación | [Matriz del piloto](real_data_pilot.md) | Aún no hay prueba integral del dominio y del ciclo de expediente | No apto para datos de clientes en producción |

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
