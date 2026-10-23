# Estado de ejecución del plan

Actualizado el 23 de octubre de 2026. El objetivo sigue siendo análisis revisable con datos reales
para el equipo y reportes por cuenta; el primer caso financiero es el piloto propio GBM BMV.

## Implementado en esta iteración

| Frente | Entrega verificable | Límite |
| --- | --- | --- |
| Navegación | Análisis, Expedientes y Guía operativa; controles agrupados y presentación adaptable | Interfaz interna; no es portal público |
| Expedientes | Perfil declarado, intermediario/producto/cartera, permisos por asignación, archivos cifrados e historial | Almacenamiento desactivado por defecto; no se migraron documentos reales |
| Revisión | Versiones, edición obsoleta rechazada, dos personas distintas del último editor de contenido, revisiones por tipo | No equivale a firma electrónica ni autoriza entrega |
| Reporte por cuenta | Resumen legible, anexo técnico y guardado explícito de PDF con parámetros y huella | El destinatario y la cuenta se verifican fuera del cálculo |
| Consolidado MXN | Valuaciones al mismo corte, identidad por ISIN/mercado, efectivo externo separado, JSON y PDF | No combina rentabilidad ni optimiza entre cuentas ni infiere comisiones agregadas |
| Piloto reproducible | Ocho archivos, contraste, Markowitz y dos simuladores; costos fechados y validaciones adicionales opcionales | Sin históricos autorizados no se calcula un caso financiero real |
| Operación | Archivo, revocación, respaldo, recuperación a ruta nueva y baja con confirmación | Claves, ACL, backups externos, baja de copias y hosting requieren configuración/verificación |
| Preparación externa | Guías de contratación de datos, revisión del servicio, privacidad y flujo de la página | No son dictámenes, licencias, contratos firmados ni autorizaciones obtenidas |

Las pruebas cubren casos sintéticos, datos futuros excluidos, versiones concurrentes, permisos,
archivos sustituidos, daños del historial, clave incorrecta, respaldo y recuperación, bajas,
asociación del PDF a una cuenta, vigencia de costos y separación de evaluación temporal.
El registro detallado y las incidencias del entorno están en [verificación](verification_log.md).

## Pendientes que dependen de evidencia o acceso externos

| Pendiente | Responsable | Se cierra con |
| --- | --- | --- |
| Cotejo del corte GBM y correspondencia documental | Titular y revisor | Hoja privada revisada y excepciones documentadas; no se inventan firmas |
| Identidad vigente e históricos locales comparables | Datos y titular | Fuentes y permisos aplicables; el borrador de cotización está preparado, sin enviar |
| Supuestos y condiciones del caso | Titular/analista | Perfil real recabado, objetivo y restricciones; tarifa aplicable y evidencia de vigencia |
| Dictamen del servicio, condiciones laborales, contratación, privacidad y fiscalidad | Titular y especialistas | Documentos y pronunciamientos revisados según el alcance real del servicio |
| Conexión opcional con la página de contacto | Responsable del sitio/desarrollo | Netlify confirmado; código/configuración y entorno identificados si se decide conectar; no impide terminar el optimizador interno |
| Configuración y prueba operativa final | Administración/desarrollo | OIDC y roles, almacenamiento persistente, custodia de claves, restauración, retención y entrega probadas |
| Primer informe real aprobado | Analista y revisores | Insumos reales completos, ejecución y revisión independiente documentadas |

No se ha contratado información de mercado, constituido una sociedad, contactado al empleador,
publicado un aviso legal, recibido documentos de nuevos clientes ni habilitado entregas a terceros.
La ejecución con datos sintéticos no sustituye ninguna de esas evidencias.

## Orden de continuación

1. Integrar el código revisado mediante PR y CI en Ubuntu/Windows; esto no habilita producción.
2. Configurar y probar el registro con expedientes sintéticos en el entorno elegido.
3. Mientras se obtienen datos y revisiones externas, realizar el cotejo privado del piloto.
4. Completar fuentes, identidades y supuestos; ejecutar el piloto propio real y revisar su informe.
5. Con el alcance del servicio y entorno validados, probar el recorrido completo de un caso
   autorizado antes de ampliar a más cuentas, intermediarios o universos.

Las diferencias históricas de centavos permanecen abiertas. No bloquean por sí mismas estudiar
una foto de posiciones, pero impiden presentar como conciliado un rendimiento realizado que
dependa de esas operaciones. No se han ajustado saldos para cuadrar la historia.
