# Calendario de valuaciones para TWR

En **Operación → Movimientos → Valuaciones necesarias para TWR** se muestra qué
cierres necesita el motor para los flujos declarados. El mismo criterio determina
si el cálculo de TWR tiene cobertura de fechas suficiente; el panel no elige
momentos de flujo ni crea valuaciones para completar el calendario.

## Qué fechas pide este motor

| Dato | Cierres necesarios |
| --- | --- |
| Periodo | Cierre inicial y cierre final distintos |
| Flujo EOD | Cierre de su fecha, posterior al flujo |
| Flujo BOD | Cierre de su fecha y del día calendario anterior |
| Flujo UNKNOWN | Cierre de su fecha; el anterior se muestra como condicional hasta confirmar BOD/EOD |

Las fechas repetidas se reúnen en una fila con sus motivos. Si una fecha condicional
también es necesaria para otro flujo BOD conocido, queda obligatoria. No se
reemplaza el cierre de un domingo por el del viernes ni se rellenan huecos.

Por ejemplo, para una aportación ficticia del lunes 5 de enero de 2026, BOD necesita
el cierre del domingo 4 y el cierre del día 5. EOD necesita el del día 5. Tener una
u otra valuación disponible no confirma cuándo se recibió el dinero. Con UNKNOWN,
TWR sigue pendiente incluso si todos los cierres posibles están aportados.

Esto describe la convención de la app. El [manual de GIPS de CFA Institute](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/)
explica diferentes metodologías y requisitos de valuación asociados a flujos
externos. Completar este calendario no constituye una declaración de cumplimiento GIPS.

## Cómo se determina el periodo

Al cargar un CSV `Fecha,NAV`, el calendario usa su primer y último cierre. Las
valuaciones deben ser positivas, finitas, con fechas sin hora ni zona horaria,
sin fechas vacías o duplicadas. Se ordenan, conservando la serie original y sin
añadir filas. Un dato con zona horaria no se convierte silenciosamente a otro día.

Antes de cargar ese CSV, el plan toma la apertura del libro y el cierre elegido;
todas las fechas siguen sin aportar. Si el libro sólo tiene un día, el panel pide
un periodo válido y no inventa un cierre posterior.

El plan utiliza las fechas de liquidación de los eventos declarados como flujos
de la cuenta: aportaciones, retiros y transferencias de efectivo o títulos. No
deduce flujos de los cambios de patrimonio ni decide si un traspaso debe eliminarse
en una consolidación; esa clasificación conserva su revisión independiente.

## Leer y descargar el plan

La tabla distingue una fecha **aportada en el CSV** de una **faltante** y separa
los cierres obligatorios de los condicionales. La descarga CSV contiene fecha,
requisito, disponibilidad y motivo; no contiene importes de patrimonio inventados.
Los flujos sin momento se cuentan individualmente, aunque compartan fecha.

La cobertura del calendario sólo revisa fechas y momentos. No acredita valores,
FX, derechos de datos, integridad del libro, aprobación de diferencias o eventos
corporativos. Un reporto vigente puede necesitar su [valor total documentado](repo_ledger.md)
y una acción un precio compatible con la base de títulos; un precio disponible
no basta por sí solo para obtener una valuación aprobada de toda la cuenta.

## TWR y XIRR

TWR conserva el encadenamiento de subperiodos y sus ajustes por flujos BOD/EOD.
El resultado incluye el mismo plan de fechas que muestra la pantalla. XIRR
continúa usando los importes y fechas de flujos, junto con los valores de inicio
y cierre; no necesita todos los cierres intermedios de TWR. Mantiene la convención
de 365 días documentada para [XIRR por Microsoft](https://support.microsoft.com/en-us/excel/functions/xirr-function)
y la comprobación conservadora existente de patrones con múltiples raíces posibles.
La suficiencia de fechas de XIRR tampoco aprueba la clasificación o los importes.
