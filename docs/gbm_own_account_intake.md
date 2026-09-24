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

La dependencia `pypdf` está en `requirements-dev.txt`; esta herramienta es una revisión local,
no un importador listo para recibir documentos de clientes. Un XML CFDI de ingreso puede servir
para contrastar cargos facturados, pero no es por sí mismo una exportación de posiciones. Si un
archivo cambia de formato o falla la lectura, el inspector lo reporta como no clasificado sin
revelar su contenido. Si se conserva la salida del caso, debe guardarse sólo en `data/private/`;
no se debe ejecutar con documentos reales en CI ni adjuntar la salida a issues o PR.

## Conciliación pendiente

1. Confirmar la relación de cada serie PDF con su contrato o subcuenta, y la relación de los XML
   con esas series. Esta clave se conservará sólo en un manifiesto privado. Nunca se deben sumar
   estados del mismo periodo por proximidad de carpeta.
2. Seleccionar una serie y un corte, extraer efectivo, reportos y renta variable con cantidad,
   instrumento, moneda, valor al corte y ubicación de página. Cotejar subtotales y valor total
   contra el PDF visible. Identificar ETF y FIBRAS por serie negociada; la etiqueta “renta
   variable” no basta para clasificarlos.
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
