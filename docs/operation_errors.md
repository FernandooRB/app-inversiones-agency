# Corregir insumos sin perder las otras herramientas

En **Operación**, un error de datos queda dentro de su pestaña. Por ejemplo, si
el CSV de NAV contiene una fecha vacía, Movimientos muestra **Revisa Valuaciones
históricas** y el motivo del rechazo. Implementación, Fuentes y alertas, Patrimonio
y Originales GBM siguen disponibles para sus tareas independientes.

Los lectores principales identifican libro, cierre, controles, cotizaciones, FX,
reportos y valuaciones históricas. El mensaje del validador se presenta como texto,
sin interpretar identificadores de archivos como enlaces o instrucciones Markdown.
Corregir o quitar el insumo vuelve a ejecutar la revisión; los cálculos mantienen
sus requisitos de datos y confirmación.

Si ocurre un fallo inesperado, la pantalla muestra una referencia de soporte.
El registro guarda área, clase de excepción y esa referencia; no guarda el mensaje
de la excepción, valores cargados ni traceback. Una validación esperada no genera
ese registro de error.

## Referencia del libro para seguimiento

El libro se reconstruye con los insumos actuales antes de que otra pestaña pueda
usar sus cantidades. Si falla la revisión activa de Movimientos, se retira esa
referencia de la sesión. No se conserva un saldo anterior como si procediera del
CSV nuevo. También se retiran los rendimientos de la vista fallida.

Cambiar el CSV del libro, su corte o abrir otra revisión recuperada exige confirmar
de nuevo las cantidades para seguimiento. Explorar la pantalla con el mismo libro
y corte conserva la confirmación explícita. Esta comprobación no acredita por sí
misma liquidación, precios, identidad ni aceptación de diferencias.

Una programación que ya tuviera una referencia guardada no se reemplaza con un
borrador inválido. El cambio no pausa ni borra programaciones existentes. Un ZIP
inválido tampoco reemplaza la revisión actual: conserva el comportamiento del
[paquete de movimientos](operations_review_package.md).

## Acceso al expediente

Los problemas de acceso o escritura del expediente interrumpen el área de Operación
para revisar la cuenta y el acceso. No se presentan como simples errores de CSV ni
se continúa con las otras herramientas bajo un contexto que falló. Una falta crítica
de memoria también interrumpe las operaciones en vez de iniciar más cálculos.

La función conserva el alojamiento gratuito y el acceso Google existentes. No
aprueba datos del piloto GBM ni resuelve sus documentos o valuaciones pendientes.
