# Consolidación de libros y monedas — Implementation Plan

> Ejecutar con superpowers:executing-plans, RED/GREEN por contrato y revisión
> independiente final. Alcance aceptado con «continua»: punto18 del roadmap.

**Goal:** conectar cortes revisados de varios libros, con corte común, FX fechado,
pertenencia declarada, conciliación y transferencias vinculadas con evidencia.
**Architecture:** reutilizar cut_state/value_book y match_internal_flows para
candidatos; sumas monetarias Decimal sobre valores nativos, sin sumar TWR/XIRR.
Paquete de consolidación independiente (esquema1), sin alterar ZIP operaciones1–5.
**Stack:** Python, Streamlit nativo y ReportLab; sin nuevas dependencias ni servicios.
**Spec:** punto18 en docs/siguientes_pasos_2026-11-15.md, AGENTS.md y preferencias
de USD0, originales reales locales, web/CI exclusivamente ficticios.

## Contratos

- Dos a diez cortes JSON, hasta2MB cada uno y10MB agregados, alias neutrales únicos
  y fuente de pertenencia por cuenta. Rechazar doble archivo/libro renombrado,
  misma cuenta repetida, contratos de otros expedientes o fechas distintas.
- Cuentas vinculadas sólo dentro del expediente autorizado y su lista de cuentas;
  revisión temporal sólo admite cortes sin vinculación, con pertenencia declarada.
- FX global: Fecha,Moneda,Base,Tasa,Fuente del corte. No invertir, interpolar,
  propagar ni reutilizar el ValorBase de otro reporte; convertir ValorOrigen una vez.
- Conservar posiciones, efectivo, pendientes y reportos por cuenta. No agrupar
  identidades de instrumentos sólo por etiqueta ni inferir emisor. NAV completo
  sólo si toda la cobertura está disponible; subtotal documentado aparte.
- Detectar candidatos por referencia/fecha/moneda/importe usando el motor existente,
  pero exigir CuentaSalida,IDSalida,CuentaEntrada,IDEntrada,Fuente para acreditar.
  Comparar importe bruto, moneda y fechas exactas; centavos/datos desconocidos
  quedan pendientes. No reutilizar una pata ni restar transferencias del NAV.
- Transferencias de títulos o entre monedas no se enlazan sin identidad/FX adicionales.
  Permanecen pendientes. Este recorrido no produce rendimiento histórico global;
  conserva métricas por cuenta con su propio periodo. La herramienta manual previa
  sigue disponible y renovará su confirmación ante cambio de insumos.
- Reabrir recupera propuestas sin confirmación/resultados. Datos originales fuera
  del ZIP, verificación de integridad y ámbito; vaciar/reemplazar no afecta otros libros.

## Tareas y puertas

1. [x] RED/GREEN: motor operations_consolidation.py, estados parciales, precisión,
   pertenencia/cortes/duplicados, FX y revisión explícita de transferencias.
2. [x] RED/GREEN: paquete independiente en memoria con límites/allowlist, lectura
   sin extracción y compatibilidad de las interfaces existentes.
3. [x] RED/GREEN: UI en Patrimonio, fuentes/formularios/CSV, confirmación renovada,
   descargas CSV/TXT/JSON/PDF de la misma ejecución y paquete bajo demanda.
4. [ ] Auditoría reproducible, revisión independiente, integración y publicación
   autorizadas. Windows/Linux, contenedor, navegadores, axe1440/768/390, archivos
   hostiles, dependencias, rendimiento, continuidad y todas las páginas del PDF.

Casos: MXN100.01+USD10×20.01=MXN300.11; falta FX→NAV pendiente y subtotal100.01.
Traspaso A−10/B+10 no cambia NAV300.11; sin vínculo/fuente no es interna acreditada.
Una diferencia .01, fechas distintas o divisas distintas impide enlazar. Valuación
de reporto ausente nunca se sustituye por capital. No se suman retornos incompatibles.

La prueba humana y en teléfono físico sigue separada de emulación. No volver a
solicitar al usuario estados o intermediarios que ya indicó que no tiene.
