# Procedimiento local de revisión inicial de documentos GBM

El piloto técnico usa estados PDF de una cuenta propia y XML de comprobantes. Los documentos,
nombres de archivo, identificadores, importes, posiciones y resultados específicos de esa cuenta
permanecen fuera del repositorio. `Estados_de_Cuenta/` y `data/private/` están excluidos de Git.
La exclusión reduce el riesgo de publicación accidental, pero no sustituye cifrado, control de
acceso ni una política de conservación.

El [inspector de entrada](../scripts/inspect_gbm_intake.py) clasifica localmente los PDF y XML y
devuelve sólo metadatos: tipo, periodos, número de páginas, presencia de un prefijo antes del
encabezado PDF, versión/tipo de CFDI y conteos por carpeta. No imprime nombres de carpetas o
archivos, RFC, cuentas, instrumentos ni montos.

```powershell
.\.venv\Scripts\python.exe scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM
```

Para comprobar sólo la portada y la continuidad de cortes del mismo contrato:

```powershell
New-Item -ItemType Directory -Force data/private | Out-Null
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-summaries > data/private/gbm_cover_validation.json
```

El control reconoce dos diseños observados de portada, comprueba que las categorías sumen los
totales inicial y final, detecta contratos mezclados en una carpeta, cortes duplicados y periodos
no contiguos, y compara el cierre de un corte con el inicio del siguiente, tanto en el total como
en las ocho categorías comunes a ambos diseños. No muestra contratos
ni importes. `EXACT` significa que esas comprobaciones cuadraron; `CENT_DIFFERENCES_NEED_REVIEW`
señala diferencias de un centavo en las categorías, y `REVIEW_REQUIRED` señala archivos sin
clasificar o discrepancias mayores. Los dos últimos estados hacen que el comando termine con
código distinto de cero para impedir que se interpreten como una aprobación automática.

Para comparar los totales de cierre del detalle con la portada y, cuando hay renta variable,
sumar sus posiciones y subtotales visibles y comprobar cantidad por precio contra valor de mercado:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-detail-totals > data/private/gbm_detail_validation.json
```

Esta opción también ejecuta el control de portada. Devuelve sólo conteos: documentos revisados,
categorías con detalle, posiciones y grupos de renta variable comprobados, así como diferencias
exactas, de un centavo o mayores. Un total faltante, ambiguo o que no coincide obliga a revisión.
La comprobación cantidad por precio redondea a centavos con la precisión impresa en el estado;
si no reproduce el valor de mercado de la fila, el documento requiere revisión.
`-X utf8` conserva los acentos válidos en el archivo JSON de salida en Windows.
Si el estado marca `CENT_DIFFERENCES_NEED_REVIEW`, el centavo debe localizarse en el documento
privado y resolverse antes de tratar el corte como conciliado. El control no identifica por sí
solo títulos, ETF, FIBRAS ni moneda de cada posición, y no compara cantidades entre cortes.

Para comprobar el saldo corrido del libro de efectivo del PDF:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-cash-ledger > data/private/gbm_cash_validation.json
```

Esta opción incluye los controles de portada y detalle. Compara el saldo inicial y final con la
portada y, para cada movimiento visible, aplica al saldo anterior el importe neto con el signo
correspondiente a la descripción de operación observada. Informa cuántas transiciones son exactas,
difieren un centavo o requieren revisión. Un tipo de operación desconocido o una fila incompleta
detiene la aprobación de ese documento. El prefijo de dos números separados por `/` no se trata
como fecha completa: la fecha de operación y la de liquidación deberán resolverse y verificarse
por separado durante la importación.

Para conciliar las cantidades visibles de renta variable con sus compras y ventas y comprobar
la continuidad entre cortes consecutivos del mismo contrato:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-equity-quantities > data/private/gbm_quantity_validation.json
```

Esta opción incluye los tres controles anteriores. Compara el cambio entre la cantidad inicial y
final de cada posición con las compraventas identificables del periodo, y la cantidad final de un
corte con la inicial del siguiente. Si una operación no se asocia de forma única con una posición,
si desaparece una posición antes del siguiente corte o si aparece un formato desconocido, exige
revisión. El control no acredita que el PDF incluya todas las operaciones ni resuelve ventas
totales sin posición al cierre, traspasos, desdoblamientos u otros eventos corporativos. Tampoco
clasifica por sí solo una serie como acción, ETF o FIBRA.

Para revisar los dos números separados por `/` al inicio de cada movimiento:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-movement-days > data/private/gbm_movement_days_validation.json
```

El control busca una fecha para el primer número dentro del periodo, respetando el orden de las
filas. Cuando un corte contiene el mismo día en dos meses, sólo acepta una fecha si el orden
permite resolverla de forma única. Comprueba que el segundo número pueda corresponder al mismo
día o a uno de los 10 días posteriores; este límite es provisional y cualquier caso fuera de él
requiere revisión. El resultado `STRUCTURALLY_PLAUSIBLE` indica únicamente que la estructura
observada es coherente. **No confirma que ambos números sean, respectivamente, fecha de operación
y de liquidación**, ni demuestra que el PDF contenga todas las operaciones. No se deben usar como
fechas definitivas en un cálculo de rendimiento, costo fiscal o recomendación hasta verificar el
significado de los encabezados y contrastar las operaciones con un registro independiente.
La opción ejecuta también los controles de portada, detalle y efectivo, de modo que diferencias
pendientes de un centavo mantienen el código de salida distinto de cero aunque los días sean
estructuralmente plausibles.

Para comprobar el neto de las compraventas visibles de renta variable contra cantidad, precio,
comisión e impuesto impresos:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-equity-trade-costs > data/private/gbm_trade_cost_validation.json
```

El control reconoce las columnas de comisión, interés, impuesto, neto y saldo. Para compras,
compara el neto con cantidad por precio más comisión e impuesto; para ventas, resta ambos cargos.
Redondea el nominal calculado a centavos con el precio impreso. Un interés no nulo, un precio no
reconocible o un formato distinto exige revisión manual; no se inventa una regla para esos casos.
La regla de venta está cubierta por documentos sintéticos, pero aún debe contrastarse con una
venta real del mismo formato antes de usarla en un expediente de cliente.
`EXACT` sólo significa que la aritmética visible cuadra. `CENT_DIFFERENCES_NEED_REVIEW` conserva
las diferencias de un centavo como pendientes, y `NO_EQUITY_TRADES` indica que no hubo filas
aplicables. El control no deduce si el impuesto corresponde a IVA, retención u otro concepto,
ni determina costo fiscal, comisiones de otros productos, liquidación o integridad de operaciones.
La opción también ejecuta los controles de portada, detalle y efectivo.

Para revisar netos de las compras y vencimientos de reporto del diseño observado:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/inspect_gbm_intake.py Estados_de_Cuenta/GBM --check-reporto-net > data/private/gbm_reporto_net_validation.json
```

En las compras, contrasta el neto con títulos por el precio unitario impreso. En los vencimientos,
resta el impuesto impreso de ese producto. Sólo admite el precio de seis decimales y las columnas
observadas; comisión en cualquier reporto, o interés o impuesto en una compra, exigen revisión
manual. Las diferencias de un centavo quedan en `CENT_DIFFERENCES_NEED_REVIEW`; una diferencia
mayor o un formato desconocido queda en `REVIEW_REQUIRED`. `NO_REPORTO_ROWS` indica que no hubo
filas aplicables. Este control **no demuestra** cómo se devengó el interés ni vincula cada compra
con su vencimiento; tampoco valida tasa, plazo, retención ni tratamiento fiscal. Para cálculos de
rendimiento debe conservarse el neto del documento y resolverse cualquier discrepancia, sin
sustituirlo por el producto recalculado. La opción también ejecuta portada, detalle y efectivo.

La dependencia `pypdf` está en `requirements-dev.txt`; esta herramienta es una revisión local,
no un importador listo para recibir documentos de clientes. Un XML CFDI de ingreso puede servir
para contrastar cargos facturados, pero no es por sí mismo una exportación de posiciones. Si un
archivo cambia de formato o falla la lectura, el inspector lo reporta como no clasificado sin
revelar su contenido. El control del saldo corrido no prueba que el PDF incluya todos los
movimientos ni valida que enumere todos los títulos. Si se conserva la salida del caso, debe
guardarse sólo en `data/private/`;
no se debe ejecutar con documentos reales en CI ni adjuntar la salida a issues o PR.

## Conciliación pendiente

1. Confirmar la relación de cada serie PDF con su contrato o subcuenta, y la relación de los XML
   con esas series. Esta clave se conservará sólo en un manifiesto privado. Nunca se deben sumar
   estados del mismo periodo por proximidad de carpeta.
2. Seleccionar una serie y un corte, extraer efectivo, reportos y renta variable con cantidad,
   instrumento, moneda, valor al corte y ubicación de página. Ya existe una comparación automática
   de totales de cierre y de los valores visibles de renta variable; falta verificar visualmente
   cada fila, sus cantidades y la clasificación. Identificar ETF y FIBRAS por serie negociada;
   la etiqueta “renta variable” no basta para clasificarlos.
3. Extraer movimientos por fecha de operación y liquidación, folio interno, tipo, cantidad,
   precio, comisión, interés, impuesto e importe neto cuando el documento los muestre. Revisar
   filas partidas entre páginas y evitar contar dos veces el movimiento de títulos y su
   contrapartida de efectivo.
4. Repetir la conciliación entre dos cortes consecutivos de la misma serie: cantidades y efectivo
   inicial + movimientos + eventos = cierre. Documentar distribuciones, retenciones, reportos,
   partidas pendientes y cualquier diferencia. Los XML pueden contrastar cargos facturados,
   pero no reemplazan el registro de operaciones ni prueban que esté completo.
5. Una segunda persona debe comprobar una muestra visual de filas y todos los totales antes de
   generar los CSV anónimos que ya acepta la app. Registrar excepciones y no liberar una cartera
   con diferencias materiales abiertas.

La [ruta del piloto](first_real_client_pilot.md) mantiene separados el ensayo técnico de cuenta
propia y cualquier entrega a clientes.
