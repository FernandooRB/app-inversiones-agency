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
no contiguos, y compara el cierre de un corte con el inicio del siguiente. No muestra contratos
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

La dependencia `pypdf` está en `requirements-dev.txt`; esta herramienta es una revisión local,
no un importador listo para recibir documentos de clientes. Un XML CFDI de ingreso puede servir
para contrastar cargos facturados, pero no es por sí mismo una exportación de posiciones. Si un
archivo cambia de formato o falla la lectura, el inspector lo reporta como no clasificado sin
revelar su contenido. El control de detalle tampoco valida operaciones ni que el PDF enumere
todos los títulos. Si se conserva la salida del caso, debe guardarse sólo en `data/private/`;
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
