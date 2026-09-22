# Importación y conciliación de la cartera actual

La aplicación puede convertir una valuación actual en MXN a pesos de cartera para compararla con
las alternativas matemáticas. El archivo vive únicamente en la sesión de Streamlit: no se guarda en
una base de datos ni crea un expediente de cliente.

El CSV debe ocupar menos de 2 MB y contener **únicamente** estas tres columnas:

```csv
FechaCorte,Instrumento,ValorMXN
2026-01-15,AAPL,60000
2026-01-15,MSFT,40000
```

`FechaCorte` usa `YYYY-MM-DD`, es igual en todas las filas y no puede estar en el futuro.
`Instrumento` debe incluir exactamente una vez cada activo del análisis, incluidos CETES, Bono M,
liquidez o fondo cuando se hayan añadido. Una posición sin saldo se incluye con valor cero.
`ValorMXN` debe ser finito y no negativo, y el total de la cartera debe ser positivo. La app
reordena las filas según el universo analizado, calcula los pesos y sustituye el capital manual con
la suma de `ValorMXN`.

La carga exige moneda base MXN y una fuente declarada. Registra en el PDF la fecha de corte, la
fuente y una huella SHA-256 abreviada; también permite descargar la conciliación ordenada con valor
y peso. No se pueden combinar el CSV y los pesos manuales en el mismo análisis.

No incluyas nombre, RFC, CURP, número de cuenta, contrato, correo ni otro identificador. La
restricción a tres columnas reduce la posibilidad de importar esos datos por error, pero el equipo
debe revisar el archivo antes de cargarlo. La conciliación comprueba estructura y aritmética; no
demuestra que la valuación sea oficial, completa, fiscal o ejecutable, ni comprueba derechos de uso.

Para cotejar el subtotal de posiciones analizadas, se puede cargar un segundo CSV de **una fila**:

```csv
FechaCorte,TotalMXN,Fuente
2026-01-15,100000.00,Estado de cuenta de ejemplo
```

La fecha debe coincidir con la cartera importada y `TotalMXN` debe ser positivo, sin separadores de
miles y con máximo dos decimales. El sistema redondea la suma de posiciones al centavo y exige igualdad
con el subtotal declarado. No debe incluir efectivo ni partidas fuera del universo importado. El archivo
ocupa menos de 100 KB, se procesa en memoria y su huella SHA-256 queda en la descripción de fuente del
PDF. Un control correcto sólo demuestra que fecha y suma coinciden con el dato transcrito.

Para comprobar la cobertura completa puede añadirse un resumen separado:

```csv
FechaCorte,ValorCarteraAnalizadaMXN,EfectivoFueraAnalisisMXN,PendienteLiquidacionMXN,OtrosFueraAnalisisMXN,TotalCuentaMXN,Fuente
2026-01-15,100000.00,5000.00,-1000.00,250.00,104250.00,Estado de cuenta de ejemplo
```

`ValorCarteraAnalizadaMXN` debe coincidir al centavo con las posiciones importadas. El efectivo es no
negativo; liquidaciones y otras partidas aceptan signo para representar cuentas por cobrar o pagar.
La suma de los cuatro componentes debe coincidir con `TotalCuentaMXN`, que debe ser positivo. El
capital optimizado continúa siendo únicamente la cartera analizada. El efectivo y las demás partidas
externas se muestran y documentan, pero no se convierten silenciosamente en un activo. Si se desea
modelar efectivo invertible, debe incorporarse como un vehículo de liquidez identificado y no volver a
incluirse como efectivo externo.

También se puede cargar un **detalle de referencia** preparado por separado desde el estado de cuenta.
Usa exactamente las mismas tres columnas que el primer CSV, con cada instrumento del análisis una vez.
La app exige la misma fecha, el mismo universo y valores iguales por instrumento al centavo; rechaza
una copia idéntica del archivo principal y detiene el análisis si algún importe difiere, aunque el
total sea igual. Se declara la fuente del detalle y se añade su huella SHA-256 al PDF. Esta comparación
no comprueba por sí sola que la transcripción corresponda al documento original ni que incluya todos
los movimientos, efectivo o posiciones fuera del universo analizado.

Ninguno de estos controles autentica el estado de cuenta. Para un caso real se debe revisar el
documento original, confirmar qué incluye cada subtotal y conciliar las operaciones y movimientos.

Cuando se requiere revisar el efecto de ventas, un [archivo fiscal separado](tax_reserve.md) aporta
el costo fiscal actualizado sin ampliar este CSV ni mezclarlo con identificadores del cliente.
