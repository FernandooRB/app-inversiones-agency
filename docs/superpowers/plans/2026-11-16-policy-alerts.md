# Avisos frente a política confirmada — Implementation Plan

> Ejecutar con superpowers:executing-plans, RED/GREEN por contrato y revisión
> independiente de la entrega completa al terminar.

**Goal:** punto17 aprobado: comparar pesos, concentración y efectivo con criterios
declarados, conservando pendientes y sin ejecutar cambios.

**Architecture:** evaluación pura de un corte validado por el motor existente;
formulario de propuestas antes de generar ZIP; snapshot único para pantalla/TXT/PDF.
ZIP v5 conserva política sin confirmación ni resultados; lectores v1–v4 intactos.

**Tech Stack:** Python/Decimal, Streamlit, ReportLab y ZIP/JSON acotados existentes.
**Spec:** alcance acordado del punto17 en `docs/siguientes_pasos_2026-11-15.md`,
respuesta anterior aceptada con «Sigamos» y AGENTS.md.

## Constraints y decisiones

- USD0; GBM real sólo local; pruebas ficticias; preservar centavos/desconocidos.
- Sin límites sugeridos activos: tolerancia, máximo individual y mínimo de efectivo
  vacíos hasta declararlos. Fuente y vigencia obligatorias para una política.
- Pesos: patrimonio neto o sólo instrumentos cotizados, denominador explícito.
  Copiar del análisis exige cuenta/identidad/corte/universo vigentes y conserva
  procedencia como propuesta; utiliza base invertida, sin conversión silenciosa.
- Efectivo disponible = liquidado menos todos los pagos pendientes, a FX del corte;
  cobros pendientes no financian el mínimo. Su porcentaje usa patrimonio neto.
- Falta de valuación/FX/reporto, política futura, objetivo ausente o criterio sin
  definir: pendiente. Un umbral se incumple estrictamente fuera de su límite.
- No inferir emisor/grupo ni sus concentraciones sin clasificación documentada.
- Cambiar datos/criterios renueva confirmación; cerrar panel retira evaluación.
- Compatibilidad ZIP v1–v4; v5 integra política propuesta ligada a cuenta/moneda.
  No originales, autorizaciones, resultados ejecutables ni rutas de módulos.

## Tasks

1. [ ] RED/GREEN: `operations_policy.py` validación acotada y evaluación sobre corte
   existente; fuente/fecha, pesos, concentración, efectivo y datos pendientes.
   Publicar `cut_state` en operations_cuts reutilizando sus validaciones.
2. [ ] RED/GREEN: ZIP v5 y recuperación/vaciado. Política única con integridad y
   scope; huellas históricas v1–v4 congeladas. Propuesta v1/v2 sigue validándose.
3. [ ] RED/GREEN: `operations_policy_ui.py` antes de download_review, inputs sin
   defaults activos, importación revisable del análisis, confirmación y CSV.
   `OperationStatus.policy_report`; pantalla/TXT/PDF mismo snapshot. PDF ≤2 páginas.
4. [ ] Pruebas de navegador, auditoría Windows/Linux, contenedor, accesibilidad
   1440/768/390, dependencias, rendimiento, seguridad, continuidad y reportes.
   Revisión independiente, integración/publicación autorizadas y prueba ficticia.

## Review focus y casos

- Compras pendientes: cash90 y pago80 no equivalen a disponible90.
- Base de pesos/cash diferentes, valuación ausente y patrimonio no positivo.
- Cuenta/universo/fechas del análisis cambiados y políticas propuestas reabiertas.
- Cambios de un centavo, igualdad exacta de umbral, objetivos no declarados.
- Archivo corrupto/hostil, cambio al colapsar panel y ZIP descargado con criterios
  del mismo rerun. Datos privados fuera de errores, CSV y PDF escapados.

La auditoría separará automatización, revisión técnica, autoinforme y teléfono
físico. Los pendientes reales y las pruebas humanas anteriores no se dan por resueltos.
