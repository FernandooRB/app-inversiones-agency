# Recuperación y copia cifrada personal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entender y recuperar lo guardado, y conservar copias cifradas locales de los ZIP existentes.
**Architecture:** Inventario común derivado de lectores actuales; UI nativa de recuperación; CLI local Fernet sin red ni cambios del motor financiero.
**Tech Stack:** Python, cryptography, pathlib, Streamlit, pytest/AppTest, Playwright/axe.
**Spec:** docs/superpowers/specs/2026-11-17-local-review-recovery-design.md

## Global Constraints

- USD 0; GBM real sólo local; ficticios en Git/CI/web.
- ZIP15MB, cifrado21MB, clave44bytes; destinos nuevos, sin enlaces/junctions.
- Lectores movimientos1–5/consolidación1, contexto explícito, consentimientos renovados.
- No borrar archivos ajenos, no escribir claves/logs privados, no inventar datos financieros.

## Review Focus

- Clave errónea, token alterado/truncado: rechazo antes de crear salida.
- Paquete de otra cuenta o ZIP hostil autenticado: validar después de descifrar.
- Destino existente o ruta con enlace: preservar contenido previo.
- Borrador sin CSV: inventario informa que todavía no incluye libro.
- Cambios de versión, caché o sesión: vista previa no conserva confirmaciones ni resultados.

### Task 1: Inventario y copia cifrada

**Files:** crear operations_recovery.py, local_review_storage.py, scripts/local_review.py,
tests/test_local_review_storage.py.
**Interfaces:** inspect_package(raw,case_id=None,account_id=None,allowed_accounts=None) devuelve inventario seguro;
movements_inventory(manifest,files) reutilizable; generate_key/save_copy/verify_copy/restore_copy/rotate_copy/delete_copy usan rutas explícitas.

- [x] Escribir pruebas de exactitud de bytes, tipos, ámbito, límites, claves, corrupción, enlaces, colisiones y borrado confirmado.
- [x] Ejecutar y observar RED; implementar mínimos con Fernet/lectores existentes y escritura exclusiva0600.
- [x] Ejecutar GREEN y CLI en proceso nuevo sin secretos en stdout/stderr.

### Task 2: Recuperación comprensible y accesible

**Files:** modificar operations_review_ui.py; crear tests/test_review_recovery.py,
scripts/check_review_recovery.cjs; conectar scripts/check_operations_browser.cjs.
**Interfaces:** movements_inventory del Task1; UI conserva etiquetas actuales, vista previa sin mutación,
guía local descargable sin claves y sin guardar resultados.

- [x] AppTest RED para inventario de libro/borrador, guía local y vista previa sin consentimientos nuevos.
- [x] Implementar inventario y límite de subida15MB; memo privado sólo de lectura con huella/contexto/código.
- [x] GREEN; navegador nativo con ZIP, inválido, teclado, capturas y axe1440/768/390.

### Task 3: Cierre auditado

**Files:** docs/local_review_recovery.md; actualizar roadmap; informe privado reproducible por entrega.

- [ ] Regresión completa, Ruff, Node, pip check/audit; Windows/Linux/Chrome/contenedor CI.
- [ ] Una revisión independiente final; corregir hallazgos materiales RED/GREEN.
- [ ] Integrar/publicar bajo autorización existente; cotejar fuentes ejecutadas y recorrido ficticio.
- [ ] Conservar evidencia automatizada/visual/humana por separado; originales y cambios ajenos intactos.
