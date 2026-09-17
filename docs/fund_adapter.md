# Preparación de fondos de inversión MXN

La aplicación acepta un CSV revisable para **un fondo y una serie exactos**. La serie importa porque
puede determinar comisiones, elegibilidad, mínimos, liquidez y derechos económicos distintos. No se usa
el nombre comercial del fondo como sustituto de la serie invertible.

## Columnas requeridas

- `Fecha`: `YYYY-MM-DD` o `DD/MM/YYYY`, con formato uniforme.
- `Fondo`: identificador constante del fondo.
- `Serie`: identificador constante de la serie.
- `Moneda`: `MXN` en todas las filas.
- `ValorAccion`: valor unitario positivo de la serie.
- `Distribucion`: efectivo por acción recibido entre la observación anterior y esa fecha; cero cuando
  no hubo distribución. La primera observación debe ser cero.

El factor de retorno total es `(ValorAccion_t + Distribucion_t) / ValorAccion_(t-1)` y el índice inicia
en 100. Esto evita perder un pago en efectivo cuando el valor de la acción cae al distribuirlo.

## Validaciones y límites

El adaptador rechaza cambios de fondo, serie o moneda, fechas duplicadas, valores faltantes, valores de
acción no positivos, distribuciones negativas y huecos respecto de las fechas de mercado en el periodo
común. La app registra fuente declarada y huella SHA-256, y permite descargar los insumos y el índice.

La aplicación no verifica que el archivo provenga de la operadora, que el valor sea ejecutable o esté
ajustado correctamente, ni las comisiones, mínimos, horarios, liquidación, impuestos, régimen, riesgos o
derechos de distribución. Estos puntos y la licencia de datos deben comprobarse antes del uso comercial.
