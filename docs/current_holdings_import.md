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
