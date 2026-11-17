# Patrimonio de libros revisados

En Operación → Patrimonio → Consolidar libros revisados, carga entre dos y diez
cortes JSON de cuentas distintas. Se exportan desde Movimientos → Comparar y guardar
cortes. Todos deben tener la misma fecha. Declara un alias neutral y una fuente que
permita cotejar la pertenencia de cada cuenta. Los cortes vinculados requieren el
mismo expediente y cuentas autorizadas; una revisión temporal sólo acepta cortes
temporales. No se modifica el libro abierto ni se mezcla el grupo con su resumen.

La confirmación corresponde a los insumos, miembros, fuentes y versión del motor.
Cambiar cualquiera de ellos retira resultados y descargas anteriores. El total sólo
aparece cuando cada componente está valuado y convertido. Un subtotal documentado
puede estar disponible mientras falta patrimonio: no es un total aproximado.

## Monedas y cobertura

Se usa el valor nativo de cada corte, convertido una vez con el FX del grupo. CSV:
`Fecha,Moneda,Base,Tasa,Fuente`. La fecha debe ser la del corte; MXN/USD y base deben
coincidir con la selección. No hay inversión, propagación ni interpolación de tasas.
El formulario prepara las mismas filas; al corregir, elimina la tasa previa.
Un CSV importado prevalece sobre el texto editable hasta quitarlo.

Se conservan por cuenta posiciones, efectivo liquidado, efectivo pendiente y valor
total documentado de reportos. El capital del reporto no sustituye su valuación.
Una etiqueta de instrumento igual en dos cuentas no acredita identidad ni emisor.
Los pesos requieren patrimonio completo positivo; un saldo nulo o negativo sigue
visible, con pesos pendientes. Los importes se suman con Decimal, sin redondear para
cuadrar. CSV/JSON conservan su precisión; pantalla/PDF formatean a dos decimales.

## Transferencias

La coincidencia de referencia, fecha, moneda e importe es sólo candidata. Para
acreditar el par se exige una fila o formulario con
`CuentaSalida,IDSalida,CuentaEntrada,IDEntrada,Fuente`, revisión confirmada, cuentas
distintas, importes brutos y moneda iguales, fechas de operación y liquidación
iguales, y patas existentes sin reutilización. Se conservan comisiones, impuestos,
referencias y momentos desconocidos. Diferencias de un centavo y vínculos sin pata
permanecen pendientes; no se inventan contrapartes. Títulos/divisas diferentes no
se enlazan automáticamente. Transferir nunca resta patrimonio.

Este recorrido muestra patrimonio al corte. No calcula rendimiento global ni suma
TWR/XIRR de cuentas con periodos/monedas diferentes. Las métricas originales siguen
en el detalle de cada cuenta. El recorrido histórico manual permanece disponible;
su confirmación también se renueva al cambiar archivos, moneda o pertenencia.

## Guardado y reportes

El paquete del grupo es independiente del ZIP de movimientos v1–v5. Esquema 1,
`kind: sig.operations.consolidation`: `consolidation.json`, cortes de cada cuenta
y CSV opcionales de FX/vínculos. Sólo datos, fuentes y huellas; no originales PDF/XML,
confirmaciones ni resultados ejecutables. La integridad no autentica un documento.
Al reabrir se comprueban límites, huellas, fechas y pertenencia; se recuperan
propuestas sin confirmar y se recalcula después de revisar. Un ZIP rechazado
conserva el grupo actual. Vaciar elimina sólo este grupo y sus cachés de sesión.

Límites: 2 MB por corte, 10 MB de cortes, 100 KB por CSV, manifiesto 32 KB,
ZIP 12 MB/13 miembros. Lectura en memoria con nombres permitidos; no se extraen
rutas del archivo al disco. ZIP repetidos, alterados, cifrados, con enlaces,
miembros desconocidos o tamaños excesivos se rechazan.

Pantalla, JSON, CSV, TXT y PDF proceden de la misma ejecución. PDF bajo demanda de
dos páginas: fuentes y avisos principales con texto acotado; JSON y CSV mantienen
el detalle íntegro. El paquete guarda las propuestas para continuar.

## Verificación y uso

`python -m pytest tests/test_book_consolidation.py` comprueba cifras independientes,
confirmaciones, faltantes, centavos, pertenencia y archivos hostiles.
`SIG_CONSOLIDATION_ONLY=1 node scripts/check_operations_browser.cjs` comprueba el
recorrido ficticio nativo; el recorrido también forma parte de la suite completa.
La auditoría por entrega registra Windows/Linux, contenedor, dependencias, acceso,
axe y revisión visual 1440/768/390, rendimiento, PDF, continuidad y publicación.
La emulación no sustituye la prueba humana ni el Samsung S23 físico con Chrome.
No habilita un intermediario nuevo ni resuelve la evidencia real GBM pendiente.
