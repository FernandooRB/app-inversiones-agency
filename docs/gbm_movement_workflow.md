# De estados GBM a rendimiento explicado

En **Operación → Movimientos → Preparar desde estados GBM**, carga los PDF del
mismo contrato y pulsa **Preparar borrador GBM**. Revisa los originales reales
localmente. Las comprobaciones web y de CI utilizan únicamente documentos ficticios.

El lector admite los diseños GBM ya observados; otros formatos, PDF escaneados o
archivos ilegibles requieren revisión y no se convierten mediante un servicio externo.
Seleccionar archivos no sustituye el libro actual. Preparar otro borrador es una
acción explícita: descarga antes el ZIP si necesitas conservar el anterior.

## Revisar propuestas

La revisión muestra primero las incidencias. Cada fila conserva huella documental,
página, fila y texto original; corregir una propuesta conserva antes/después, motivo,
fuente y fecha. Los tipos, instrumentos y fechas extraídos son propuestas que debes
cotejar. El momento de un flujo permanece `UNKNOWN` hasta que conste su tratamiento.

Los PDF repetidos se importan una vez. Los estados posteriores aportan controles de
continuidad; no reinician el efectivo ni los títulos. Los contratos mezclados se
rechazan y los periodos discontinuos o solapados conservan una incidencia.

**Añadir movimiento respaldado** permite declarar una apertura o movimiento no
extraído, con su fuente y motivo. Estas entradas se identifican como manuales.
No se generan ajustes para hacer coincidir saldos ni se inventan devengos de reportos.

Para usar el libro deben estar resueltas las incidencias de normalización y deben
estar disponibles los originales coincidentes. Confirma cuenta, moneda, fechas,
importes, cargos y clasificación y pulsa **Usar movimientos revisados**. La
validación reutiliza el motor Decimal existente, incluidos sus controles de
compraventas, referencias de reportos, liquidación y posiciones cortas.

## Completar y entender

Puedes completar controles, cotizaciones, valuaciones históricas, FX y valores
totales de reportos con sus formularios o con los CSV existentes. Guardar un dato
reemplaza la misma clave de fecha/referencia y conserva las demás filas. Cada dato
nuevo requiere fecha y fuente; las confirmaciones se renuevan.

**Cuánto gané y por qué** separa patrimonio, aportaciones, retiros y ganancia.
Los ingresos y cargos se desglosan cuando su moneda permite compararlos; el resto
se identifica como variación no desglosada. Las cifras no disponibles permanecen
pendientes. TWR requiere sus valuaciones y momento de flujo; XIRR conserva sus
requisitos propios y se presenta anualizada. Una aportación no es una ganancia.

La coincidencia de fechas o de aritmética no aprueba fuentes, contrapartes o eventos
corporativos. Una diferencia de centavos permanece en los controles y no se oculta
al importar el siguiente estado. Los pendientes reales del piloto GBM no se resuelven
mediante una suposición del software.

## Guardar y continuar

El PDF breve se prepara bajo demanda desde **Archivos y resumen descargable** y
usa la misma explicación que la pantalla. Conserva alcance y pendientes; el TXT
contiene el detalle de la revisión.

El ZIP versión 2 conserva los CSV disponibles, el borrador, las correcciones y su
procedencia. Incluye el resumen TXT del estado al descargarlo. Puede guardar un
borrador incompleto sin libro. Los PDF/XML quedan fuera; el archivo contiene datos
privados sin cifrar y debe custodiarse como el original.

Se siguen leyendo los paquetes versión 1. Reabrir un ZIP no restaura aprobaciones:
las confirmaciones se renuevan. Para volver a usar un borrador documental debes
adjuntar los originales; además de sus huellas se vuelve a comprobar que las filas
de procedencia no fueron omitidas o alteradas. Los resultados se recalculan.

## Verificación de cada entrega

El criterio de cierre del proyecto exige auditorías funcionales, económicas, de
seguridad, privacidad, dependencias, accesibilidad, diseño, rendimiento, continuidad,
PDF y publicación. Los resultados deben distinguir verificado, corregido, pendiente
y no comprobado. La emulación de teléfono y las pruebas automáticas se registran
separadamente de las pruebas con una persona y un dispositivo físico.
