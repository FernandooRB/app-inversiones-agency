# Estado y pendientes de la revisión

**Probar con datos ficticios** abre un [caso demo](operations_demo.md) en otra
pestaña para practicar este recorrido conservando la revisión de origen.

Operación abre con el alcance de la sesión o cuenta, el corte del libro, la moneda
y el periodo del rendimiento cuando existe calendario. El panel reúne los
pendientes detectados por las comprobaciones actuales; la acción principal abre
la herramienta del primer pendiente. Los controles de cierre y el calendario
se despliegan cuando son el destino. Las otras herramientas siguen disponibles.

La lista muestra motivo, estado, evidencia y siguiente acción. Conserva cada
diferencia y saldo sin control en su unidad original. Identifica cierres
obligatorios y condicionales, momentos UNKNOWN y confirmaciones aún pendientes.
Los traspasos declarados no acreditan por sí mismos una pareja entre cuentas.
Si se cargan originales GBM, sus diferencias y revisión documental también
aparecen en la lista. Esto no vincula automáticamente un original con el libro.

Se muestran primero hasta tres pendientes; **Ver todos los pendientes** permite
consultar el resto en páginas de hasta diez filas. La evidencia muestra una huella
corta; el resumen descargable conserva los SHA-256 completos. Un estado de coincidencia aritmética o un cálculo disponible
no sustituyen la revisión humana. No hay un porcentaje de aprobación ni una
acción que cree ajustes para cuadrar los saldos.

## Descargar el mismo resumen

En **Archivos y resumen descargable**, **Descargar resumen de revisión** entrega
un TXT legible con alcance, corte, moneda, saldos, pendientes, resultados y
calendario del motor, huellas de insumos y versión del código. El texto conserva
los identificadores como texto plano. Es un archivo privado de la sesión actual.
Los saldos no se suman entre monedas y el capital de reporto no se presenta como
su valor total o NAV.

El panel y el TXT se construyen con el mismo objeto nuevo en cada ejecución.
No vuelven a calcular conciliación o rendimiento. Quitar o reemplazar un insumo
actualiza sus hallazgos; otra cuenta no reutiliza los de la anterior. Si falla
Movimientos, el resumen conserva el rechazo y retira sus saldos y resultados.
Cuando el acceso al expediente o un fallo crítico interrumpe el área, el panel
no se presenta como una revisión completada.

El resumen abarca las etapas alcanzadas por esta ejecución. Un archivo rechazado
puede impedir revisar los insumos posteriores; corregirlo permite continuar.
Las confirmaciones siguen las reglas del libro y del
[paquete de movimientos](operations_review_package.md). El TXT informa; el ZIP
conserva los CSV necesarios para retomar la revisión. Ninguno aprueba el piloto GBM.

La función mantiene el alojamiento gratuito, Google y la conservación temporal
existentes. Las pruebas automatizadas y visuales utilizan únicamente datos ficticios.
