# Preparación de vehículos de liquidez MXN

La aplicación acepta un CSV revisable para **un solo vehículo identificado**. Puede representar una
cuenta remunerada o un vehículo de disponibilidad diaria cuando la fuente proporciona una tasa anual
histórica. No convierte la tasa vigente hoy en una historia ficticia ni trata el saldo como acción.

## Columnas requeridas

- `Fecha`: `YYYY-MM-DD` o `DD/MM/YYYY`, con un formato uniforme.
- `Vehiculo`: nombre constante del contrato, cuenta o producto analizado.
- `TasaAnualPct`: tasa anual expresada en porcentaje; por ejemplo, `8.50` significa 8.50%.
- `Convencion`: `nominal_360` o `efectiva_365`, constante en todo el archivo.
- `Tratamiento`: `BRUTA` o `NETA`, constante y declarado por quien aporta los datos.

La tasa observada en la fecha anterior se aplica a los días calendario transcurridos hasta la fecha
actual. Para `nominal_360`, el factor es `1 + tasa × días / 360`. Para `efectiva_365`, el factor es
`(1 + tasa) ** (días / 365)`. El primer nivel del índice es 100.

## Validaciones y auditoría

El adaptador rechaza fechas duplicadas o inválidas, cambios de vehículo, convención o tratamiento,
tasas faltantes y factores no positivos. La integración exige cada fecha del mercado dentro del periodo
común; no rellena huecos. El reporte registra fuente declarada y una huella SHA-256, y la app permite
descargar tasa, días aplicados e índice acumulado.

`NETA` no significa que la app haya calculado impuestos o comisiones: sólo conserva la declaración del
archivo. Antes de usar el resultado deben verificarse el contrato, la metodología de la tasa, horarios,
disponibilidad, saldos mínimos, comisiones, impuestos, riesgo de crédito, protección aplicable y derechos
de uso de los datos.
