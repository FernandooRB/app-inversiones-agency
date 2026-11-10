# Caso demo de Operación

En **Operación**, **Probar con datos ficticios** abre una pestaña de práctica.
La revisión de origen conserva su sesión, archivos y confirmaciones. El enlace
usa el mismo alojamiento y la entrada del demo mantiene el acceso Google.

El caso carga automáticamente un libro MXN, un control de cierre y un CSV de
valuaciones. Empieza con 100 MXN y una aportación de 50 MXN al cierre del 5 de enero
de 2026. El libro llega a 150 MXN, el control indica 150.01 y falta una fecha en
el NAV. Los importes son ficticios y reproducibles; no se consultan cotizaciones.

## Recorrido

1. Revisa el panel y la diferencia del control; conserva los importes originales.
2. En **Guía de práctica**, descarga **Valuaciones completas del demo** y carga
   ese CSV en **Valuaciones históricas verificadas**, dentro de Movimientos.
3. Cuando el panel indique **Revisar y confirmar los flujos**, abre **Revisión de
   flujos y resultado** y revisa los datos antes de marcar la confirmación. Tener
   las fechas completas no confirma los importes. Con el calendario completo, el caso
   produce ganancia de 0 MXN y TWR de 0%: la aportación no se cuenta como ganancia.
4. **Abrir resumen descargable** despliega **Archivos y resumen descargable**;
   descarga el TXT. El archivo y su alcance
   indican **DEMO**; el control con diferencia conserva su revisión pendiente.

La guía también incluye un CSV con fecha inválida para practicar el rechazo y
la recuperación. **Reiniciar datos de práctica** repone los archivos iniciales
y exige renovar las confirmaciones dentro del demo.

## Alcance

La práctica ejecuta sólo Movimientos. Las otras pestañas no leen análisis,
propuestas, catálogos ni documentos reales. No abre expedientes ni guarda
evidencias en ellos; tampoco importa o exporta paquetes ZIP. El TXT de práctica
mantiene su marca DEMO. Para volver a la revisión original, cierra la pestaña.

El alojamiento y las dependencias se conservan. Las pruebas automatizadas cubren
la separación de sesiones, la corrección, las confirmaciones, el resumen y el
reinicio. No equivalen a medir la comprensión de una persona. Para esa medición,
usa el [protocolo de prueba](operations_usability.md).
