# CSV Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mapear un CSV a un borrador de libro conservando origen, decisiones y pendientes al reabrir.
**Architecture:** Motor puro de correspondencia y procedencia; UI nativa de propuesta; ampliación opcional del ZIP a v6, reutilizando lectores/cálculos actuales.
**Tech Stack:** Python csv/Decimal, Streamlit, pytest/AppTest, Playwright/axe; sin dependencias nuevas.
**Spec:** docs/superpowers/specs/2026-11-24-csv-mapping-design.md

## Global Constraints

- Alojamiento USD 0; reales sólo locales y ficticios en Git/CI/web; preservar cambios ajenos.
- CSV 2 MB/20,000 registros/40 columnas/2,000 caracteres por celda; JSON 100 KB; ZIP 15 MB.
- Sin ceros, fechas, clasificaciones, contrapartes o asientos inventados; no redondear importes.
- Mantener lectura movimientos v1–v5, consolidación v1 y cifrado local.

## Review Focus

- Importe neto y cargos separados: conservar valores y bloquear incompatibilidad, sin cuadrar.
- Fecha 02/03 y números 1.234,56: interpretación explícita, nunca adivinada.
- Archivo nuevo con mismo nombre/cabeceras: retirar decisiones de fila y confirmaciones.
- Repeticiones económicas con IDs distintos: resolución explícita, sin sumar silenciosamente.
- Fuente/mapeo cambiado tras usar libro: edición independiente y reemplazo informado, sin vínculos falsos.

### Task 1: Correspondencia y procedencia

**Files:** crear csv_mapping.py, tests/test_csv_mapping.py.
**Interfaces:** read_source(raw,delimiter,encoding); blank_mapping(headers); preview(raw,mapping,decisions);
pack_import(proposal)/unpack_import(meta,source,case_id,account_id); write_template/read_template.

- [ ] RED: dinero independiente con aportación/retiro/dividendo/cargos/compra pendiente, formatos explícitos, magnitud, desconocidos, duplicados, exclusiones, límites y fórmulas.
- [ ] Implementar motor puro y validar con Event/read_ledger/book_at; preservar bytes y rangos de líneas.
- [ ] GREEN enfocado y comprobación de JSON de datos sin decisiones reutilizables por error.

### Task 2: Paquete v6 y revisión conectada

**Files:** modificar operations_review.py, operations_review_ui.py, operations_recovery.py,
local_review_storage tests/docs cuando corresponda; crear tests/test_csv_mapping_portable.py.
**Interfaces:** csv_import opcional de construcción; manifest csv_import_data al leer;
csv_import_draft() y set_csv_import(...,ledger=None,cutoff,base) invalidan sólo contexto actual.

- [ ] RED: parcial/aplicado, ZIP alterado/ámbito ajeno, vínculo de origen, TXT visible y compatibilidad1–6.
- [ ] Implementar miembros acotados de mapping y confirmaciones renovadas; nunca deserializar resultados.
- [ ] GREEN; guardar/reabrir/cifrar y preservar cuentas ajenas.

### Task 3: UI y cierre

**Files:** crear csv_mapping_ui.py, tests/test_csv_mapping_ui.py, scripts/csv_mapping_fixture.py,
scripts/check_csv_mapping.cjs, docs/csv_mapping.md; conectar operations_ui.py y navegador completo.

- [ ] RED AppTest: propuesta sin sustituir, campos pendientes, formulario de decisiones actual, colapso, reemplazo y cuenta distinta.
- [ ] Implementar columnas/valores explícitos, vista previa y acciones guardado/uso; muestra bruto/cargos y fuente.
- [ ] GREEN y navegador real ficticio con tipos/decimales/fechas, ZIPv6 y teclado/axe1440/768/390.
- [ ] Una revisión independiente, corregir materiales RED/GREEN, regresión Windows/Linux, contenedor, dependencias y PDF.
- [ ] Integrar/publicar bajo autorización vigente, cotejar código ejecutado y mantener registros humanos/físicos aparte.
