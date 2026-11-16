# Propuesta portátil y actualizaciones verificables

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Ejecutar las tareas y conservar evidencia por entrega.

**Goal:** Conservar, retomar y explicar una propuesta sin perder fuentes ni restaurar aprobaciones.

**Architecture:** Extender el paquete a v3, manteniendo lectores v1/v2. Un módulo puro valida y serializa la propuesta; pantalla, CSV y PDF consumen la ejecución vigente. Reutilizar únicamente cotizaciones con instrumento, moneda, corte y fuente coincidentes. Comprobar módulos ejecutados antes de importar las áreas de trabajo.

**Tech Stack:** Python 3.12, Streamlit, pandas, SciPy y ReportLab existentes; sin servicios nuevos.

**Spec:** docs/siguientes_pasos_2026-11-15.md, puntos 08–10, 19–20 y recuperación de 24. El resto de la hoja de ruta conserva su orden y sus dependencias externas.

## Global Constraints

- Alojamiento USD 0; originales y resultados reales locales, web/CI ficticios.
- No restaurar consentimientos ni tratar resultados guardados como una ejecución vigente.
- Leer paquetes v1/v2 sin cambiar sus campos ni huellas históricas.
- Mantener diferencias y datos desconocidos; conservar cambios ajenos.

## Review Focus

- ZIP válido cuyo resultado ha sido manipulado: permanece histórico y sin aprobación.
- Libro reemplazado tras preparar una propuesta: retirar resultado y confirmación.
- Precio con moneda/fecha diferente o duplicado: no precargarlo.
- Módulo importado cuyo archivo cambia con proceso activo: bloquear antes de ejecutar mezcla.
- Importación de un paquete en otra identidad/cuenta o tras vaciar: ninguna exposición cruzada.

### Task 1: Propuesta portable v3

**Files:** operations_proposal.py, operations_review.py, tests/test_operations_proposal_portability.py.

**Interfaces:** `portable_proposal(proposal) -> dict`; `validate_proposal(payload) -> dict`; `build_operations_review(..., proposal=None)`; `read_operations_review(...)` conserva contrato y devuelve proposal_data opcional.

- [ ] Escribir pruebas de roundtrip, entradas/tarifas/fuentes completas, versiones antiguas, integridad, campos hostiles, separación de cuenta y resultados sin consentimiento.
- [ ] Ejecutar y observar fallo por interfaz ausente.
- [ ] Implementar validación acotada sin optimizar al leer; hashes y miembros permitidos v3.
- [ ] Ejecutar pruebas enfocadas y regresión de paquetes.

### Task 2: Recuperación, cotizaciones y PDF

**Files:** operations_proposal_ui.py, operations_review_ui.py, operations_ui.py, operations_proposal.py, operations_report.py, tests/test_operations_proposal_portability.py, scripts/check_gbm_review.cjs.

**Interfaces:** `reviewed_quote_defaults(raw, assets, cutoff, currency) -> dict`; `proposal_pdf(payload, snapshot=None) -> bytes`. Reabrir ofrece insumos y renueva confirmaciones; sólo recalcular produce resultado vigente.

- [ ] Probar precios con fuente/fecha/moneda exacta, duplicados, recuperación y retiro al cambiar el libro o las tarifas.
- [ ] Implementar prefills sin inventar lotes/pesos, ZIP completo y PDF de propuesta bajo demanda con cifras de la misma ejecución.
- [ ] Probar exportación nativa y reabrir en otra sesión; revisar PDF renderizado y dispositivos emulados 1440/768/390.

### Task 3: Arranque y coherencia de módulos

**Files:** runtime_coherence.py, app_inversiones.py, tests/test_runtime_coherence.py, scripts de medición.

**Interfaces:** `loaded_module_changes(root) -> list[str]`, comprobación antes de imports funcionales. Capturar huellas del código cargado y comparar con disco; no recargar módulos con sesiones activas.

- [ ] Prueba en proceso vivo: importar, modificar archivo, detectar mezcla antes de usarla; nueva ejecución limpia funciona.
- [ ] Mover importaciones de análisis avanzado después de selección de área; medir arranque e interacciones por separado con condiciones equivalentes.
- [ ] Mantener acceso y errores sin datos privados; explicar reinicio y conservar ZIP.

### Task 4: Auditoría e integración

- [ ] Suite completa Windows/Linux, Ruff, dependencias y contenedor.
- [ ] Auditoría de cálculos independientes, ZIP hostiles/compatibilidad/recuperación, privacidad, navegador, accesibilidad, rendimiento y PDF.
- [ ] Revisión independiente del cambio y corrección verificada de hallazgos relevantes.
- [ ] Integración/publicación autorizadas; comprobar versión realmente ejecutada con datos ficticios.
- [ ] Actualizar hoja de ruta e informe con verificado/corregido/pendiente/no comprobado. Conservar separadas pruebas humanas y automatizadas.
