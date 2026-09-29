# Alcance de una cuenta para tarifas por orden

El primer reporte con tarifas distintas por instrumento se prepara para **una sola cuenta**.
Un futuro consolidado combinará reportes ya conciliados por cuenta; no agregará operaciones
entre cuentas antes de comprobar qué intermediario y comisión corresponde a cada una.

Al cargar [reglas de tarifas por orden](broker_tariffs.md#reglas-por-orden), la interfaz exige
un manifiesto CSV de una fila. El botón **Descargar manifiesto de alcance prellenado** inserta las
huellas SHA-256 completas de los archivos cargados. El equipo debe completar el alias,
intermediario, fecha de corte si hay cartera y referencia de alcance. No uses nombres, RFC,
correos ni números reales de cuenta; `Cuenta_A` es sólo un alias del análisis.

```csv
AliasCuenta,Intermediario,PuntoPartida,FechaCorte,FechaRevision,HuellaCarteraSHA256,HuellaTarifasSHA256,FuenteAlcance
Cuenta_A,GBM,CARTERA,AAAA-MM-DD,AAAA-MM-DD,EDITAR_SHA256_CARTERA,EDITAR_SHA256_TARIFAS,Estado revisado
```

- `PuntoPartida=CARTERA` requiere el CSV de cartera valuada en MXN. Su fecha de corte y huella
  completa deben coincidir exactamente con el archivo cargado. No se aceptan pesos manuales.
- `PuntoPartida=EFECTIVO` requiere que no se cargue cartera; `FechaCorte` y
  `HuellaCarteraSHA256` quedan vacías. El capital parte de efectivo.
- `Intermediario` debe coincidir con todas las reglas por orden. Un solo manifiesto no puede
  mezclar tarifas de distintas casas de bolsa.
- `FechaRevision` no puede ser futura ni, para una cartera, anterior a su corte.
- `HuellaTarifasSHA256` debe coincidir con el CSV exacto de reglas, incluidos saltos de línea.
  Cambiar el archivo obliga a descargar o regenerar el manifiesto.
- `FuenteAlcance` identifica de forma no personal el documento o revisión con que el equipo
  asoció los archivos a una cuenta. El manifiesto se procesa sólo en memoria; los PDF muestran
  alias, intermediario, fuente, fecha de revisión y huellas abreviadas.

Una huella coincidente evita sustituir accidentalmente un archivo por otro. **No demuestra**
que la cartera, estado y convenio pertenezcan a la misma cuenta, ni que el cliente cumpla un
tramo de volumen o una tarifa negociada. Eso exige revisar los originales y el contrato de esa
cuenta. El sistema tampoco detecta si un CSV de cartera ya combina varias cuentas bajo un mismo
símbolo: el equipo debe separarlas antes de importarlas.

El flujo del piloto GBM es: identificar una serie de estados de la misma subcuenta, preparar una
cartera de esa serie, seleccionar sólo las reglas aplicables a ella, crear el manifiesto y revisar
el PDF por cuenta. Los estados y convenios originales permanecen en el expediente privado; los
CSV de trabajo no se publican en el repositorio. El consolidado posterior requerirá reglas
explícitas de agregación y reconciliación de saldos y cargos entre reportes terminados.
