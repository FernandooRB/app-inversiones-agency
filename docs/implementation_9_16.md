# Trabajo de las prioridades 9 a 16

Base: rama `codex/portfolio-operations-9-16`, entrega 1–8 conservada en `8b70012`.

| Punto | Entrega que se verificará |
| --- | --- |
| 9 | Contenedor y configuración Render con disco persistente, comprobación de configuración, respaldo/restauración y una versión revisable |
| 10 | Piloto propio GBM BMV sobre documentos autorizados, con procedencia y diferencias visibles |
| 11 | Movimientos normalizados, cantidades/efectivo/pendientes de liquidación, valoración y rendimiento separado de flujos |
| 12 | Optimización con costos y límites de rotación, cantidades/lotes y presupuesto de efectivo |
| 13 | Importación revisable PDF/XML/CSV y actualización de fuentes aprobadas con antigüedad visible |
| 14 | Catálogo de identidades de emisor y componentes fechados, actualización y cobertura de exposición |
| 15 | Revisiones periódicas y alertas persistentes dentro de la app, deduplicadas por cambio relevante |
| 16 | Consolidación MXN/USD con FX explícito, cobertura y eliminación de transferencias internas verificadas |

También se incorporarán nombres y fechas legibles de ejecuciones, selección reciente, borradores
cifrados, conservación de navegación y medidas operativas sin contenido privado.

El destino recomendado es Render con cómputo de 1 CPU/2 GB y disco persistente. El despliegue real
requiere la cuenta de alojamiento, secretos OIDC y autorización del costo concreto. El piloto elegido
es la cuenta propia GBM BMV. Los originales se localizaron en la carpeta autorizada por el usuario
y se revisaron dos cortes consecutivos y un CFDI, sin incorporarlos a Git. El informe privado
conserva las diferencias y los pendientes de revisión humana. El despliegue real y la aceptación
humana del piloto no se consideran completados por pruebas ficticias.

Implementación y uso: `docs/operations_9_16.md`. La evidencia de pruebas de navegador está en
`outputs/operations_review_2026-11-06/`; el piloto permanece exclusivamente en `data/private/pilot_gbm/`.

Validación local de la entrega:

- 684 pruebas completas aprobadas, incluida restauración de casos/borradores y seguimiento.
- Recorrido de análisis, PDF, archivo y reapertura comprobado en navegador.
- Operación comprobada en 1440, 768 y 390 px, sin excepciones ni desbordamiento horizontal.
- Inspector visual sin fallos; advertencias de bordes de controles nativos y tablas auxiliares
  de accesibilidad. Las cifras visibles se revisaron y se muestran alineadas a la derecha.
- Blueprint validado sin errores contra `https://render.com/schema/render.yaml.json`.
- Construcción local del contenedor pendiente: Docker Desktop tiene el motor detenido.
  La rama incluye una comprobación de construcción y arranque cerrado en GitHub Actions.
- No se ha activado un alojamiento ni enviado documentación real a servicios externos.
