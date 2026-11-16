# Estrategia elegida y comparación realizable

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Ejecutar inline y revisar la rama completa al terminar.

**Goal:** Llevar una alternativa calculada de la misma cuenta a títulos, comparar conservar/cambio parcial/propuesta y medir la exposición final después de costos.

**Architecture:** Un módulo puro verifica la ejecución de cuenta y conserva su procedencia. Reutiliza el motor de lotes para dos alternativas, conserva una referencia sin transacciones y evalúa medias/volatilidad con el modelo existente. La pantalla conserva la ejecución y descarga su comparación sin resolver al navegar. El paquete v4 transporta la procedencia de estrategia con una propuesta schema2; v1/v2/v3 y propuestas schema1 siguen legibles.

**Tech Stack:** Python, Streamlit, pandas, NumPy, SciPy y ReportLab existentes; ninguna dependencia o servicio nuevo.

**Spec:** `docs/siguientes_pasos_2026-11-15.md`, puntos 11–13. Uso personal y auditoría obligatoria de `AGENTS.md`. La petición «Sigamos» continúa el bloque anunciado; las decisiones siguientes son de implementación, no preferencias nuevas atribuidas al usuario.

## Global Constraints

- Alojamiento USD 0; originales y resultados reales locales, web/CI ficticios.
- Conservar evidencia, centavos, desconocidos y cambios ajenos.
- Confirmar antes de calcular; cambiar insumos/estrategia/ejecución retira aprobación y resultados.
- No convertir historia ajustada en precio para operar; no enviar órdenes.
- Al abrir ZIP los resultados son históricos; renovar confirmaciones.

## Decisiones

Se reutilizan alternativas de Análisis de cuenta; duplicar el optimizador en Operación crearía objetivos distintos. El usuario elige entre pesos del insumo y una alternativa de su análisis vigente. La selección no activa automáticamente un cálculo. Un objetivo nuevo por costos sigue siendo una opción explícita separada, incompatible con mantener la estrategia elegida sin cambiarla.

Conservar mantiene títulos y efectivo exactos, sin cargos de transacción. Los límites incumplidos se muestran. Cambio parcial interpola los pesos actuales sobre capital inicial hacia el objetivo con fracción explícita (25% inicial); no aplica una fracción de órdenes redondeadas. El motor calcula ambos cambios con los mismos precios y tarifas. Una alternativa inviable conserva su motivo; no se sustituye por cero.

Riesgo: pesos finales sobre patrimonio después de cargos, con el efectivo separado. Medias y covarianza son las del análisis, y se muestran fechas/observaciones/estimador. El efectivo se supone constante en este modelo nominal; no se generaliza a riesgo de contraparte, inflación o FX. Sin cobertura coincidente el riesgo queda pendiente. No se anualiza el cargo inicial como si fuera rendimiento recurrente.

El ZIP conserva estrategia, periodo, universo, pesos, run/key/versión y huellas de insumos, además de la propuesta. La comparación CSV es una descarga separada. Para volver a evaluar riesgos se necesita el análisis de cuenta; no se restaura su aprobación ni se inventa historia desde el ZIP.

## Review Focus

- Misma cuenta pero otra identidad/store: rechazar conexión de estrategia.
- Análisis anterior con cambios sin calcular: rechazar conexión.
- Universo igual con distinto orden, moneda o corte: rechazar sin reordenar silenciosamente.
- Conservar fuera de límites o alternativa inviable: mostrar referencia/incidencia, sin ocultarla.
- Liquidez residual, cargos, falta de modelo o datos parciales: denominadores correctos y riesgos pendientes.

### Task 1: Vinculación y motor comparativo

**Files:** Crear `operations_comparison.py`, `tests/test_operations_comparison.py`.

**Interfaces:** `strategy_from_analysis(flow, binding, assets, cutoff, currency, name) -> dict`; `validate_strategy(value, assets, cutoff, currency, target) -> dict`; `compare_plans(positions, cash, target, assumptions, *, fraction=.25, **limits) -> dict`; `plan_risk(plan, model) -> dict`.

- [ ] Escribir pruebas: cuenta/actor/store/corte/orden incorrectos, insumos obsoletos y cambio de versión; verificar RED.
- [ ] Implementar procedencia acotada, sin copiar originales ni datos de identidad al paquete.
- [ ] Caso independiente: efectivo1000, precio10, objetivo40%, comisión10pb: conservar1000/costo0; parcial10 títulos/costo0.10/efectivo899.90; propuesta40/costo0.40/efectivo599.60.
- [ ] Probar referencia concentrada, fracción0/1, inviabilidad y riesgos postcosto: valor600, efectivo399, media10%, varianza4% → peso600/999, media0.1×600/999, volatilidad0.2×600/999.
- [ ] Implementar y ejecutar regresión enfocada.

### Task 2: Pantalla, procedencia y recuperación

**Files:** Modificar `operations_ui.py`, `operations_proposal.py`, `operations_review.py`, `operations_review_ui.py`; crear pruebas AppTest en `tests/test_operations_comparison.py`.

- [ ] Probar RED selección alternativa→pesos efectivos; invalidación por estrategia/ejecución/cuenta; no resolver al descargar/navegar.
- [ ] Añadir selección explícita de origen del objetivo y fracción parcial; mostrar comparación debajo del resultado vigente y detalle desplegable. Riesgos pendientes cuando falta análisis compatible.
- [ ] Probar RED roundtrip v4, esquema estricto de procedencia, huella/target/fecha alterados; lectura de ZIP v1/v2/v3 sin cambiar sus conjuntos de módulos.
- [ ] Conservar procedencia en propuesta schema2/v4 y PDF sin exceder dos páginas; recuperar como histórico y exigir recálculo. Descargar matriz CSV por separado.

### Task 3: Auditoría e integración

**Files:** `scripts/check_gbm_review.cjs` y nuevo recorrido ficticio de comparación si conviene; guía y hoja de ruta. Evidencia local en `data/private/deployment/community_cloud/strategy_comparison_2026-11-16`.

- [ ] Suite Windows/Linux, Ruff, pip check/pip-audit, contenedor y navegador; revisar regresiones y casos independientes.
- [ ] Revisar privacidad, continuidad v1–v4, sesiones/cuentas, accesibilidad axe y capturas 1440/768/390; medir cálculo frente a navegación.
- [ ] Renderizar/abrir todas las páginas PDF, comparar pantalla/CSV/ZIP; revisión independiente y correcciones verificadas.
- [ ] Integrar/publicar dentro de la autorización vigente, comprobar versión y recorrido ficticio publicado. Separar uso humano/S23 físico y evidencia real pendiente.
