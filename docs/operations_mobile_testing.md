# Comprobación móvil de Operación

El recorrido de navegador incluye una sesión aislada de Chromium con pantalla
de 390 × 844, modo móvil y soporte táctil. Ejecuta acciones con `tap`, carga
archivos mediante el selector de Chromium y guarda las descargas del caso
ficticio. No necesita nuevas dependencias ni un servicio de pago.

## Qué comprobar

- Abrir el demo desde una revisión con archivos y confirmaciones propios.
- Completar el CSV de valuaciones sin confirmar automáticamente los flujos.
- Revisar y confirmar antes de obtener el rendimiento.
- Descargar un TXT marcado DEMO con la diferencia de −0.01 MXN aún pendiente.
- Reiniciar la práctica y conservar la revisión original.
- Mantener los controles legibles, accesibles con toque y sin desbordamiento
  horizontal de la página. El registro incluye sus dimensiones.

En pantallas de hasta 640 px, los botones de acción, descarga y carga, los enlaces
de acción, las pestañas, el selector de área, los desplegables y las etiquetas de
confirmación tienen una zona mínima de 44 × 44 px. La presentación de escritorio
conserva sus dimensiones. El recorrido táctil comprueba el tamaño de los
controles que utiliza, además de su funcionamiento.

El fixture usa exclusivamente archivos ficticios en un servidor local del
ejecutor de pruebas. El contexto se cierra al terminar, incluso ante un fallo.
Las capturas y el registro `touch_verification.json` se conservan como artefactos
del flujo **Operations browser**. Un fallo conserva diagnóstico separado.

## Qué requiere un teléfono real

La emulación no comprueba Safari/iOS, el selector de archivos de Android o iOS,
el inicio de sesión desde ese dispositivo, su teclado ni su almacenamiento.
Tampoco mide comprensión, dudas o tiempos de una persona. Para esa parte, utiliza
el [protocolo de uso](operations_usability.md) y registra dispositivo, navegador,
tareas terminadas y ayudas recibidas.

Una persona que ya conoce el caso participa en una repetición. Sus resultados
deben distinguirse de los de alguien que lo intenta por primera vez. Si no hubo
medición del tiempo, conserva ese campo vacío.
