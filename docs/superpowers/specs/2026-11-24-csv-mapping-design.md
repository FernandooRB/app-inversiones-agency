# CSV revisable hacia el libro común

Continuación del punto 27 autorizado: uso personal, GBM primero, fuentes reales
sólo locales, pruebas ficticias en Git/CI/web y alojamiento USD 0. No se anuncia
un segundo intermediario ni se inventan formatos de estados de cuenta.

La pantalla responde «¿cómo corresponden mis columnas al libro y qué falta?».
Se conserva Streamlit, los controles nativos y el diseño actual de SIG. Muestra
original, correspondencia, resultado propuesto e incidencias antes de reemplazar
la revisión. Importe bruto, cargos, fechas, moneda y clasificación se declaran;
no se deducen netos, contrapartes, momentos de flujo ni importes cero.

Se consideró transformar fuera de la app, crear un paquete separado y ampliar el
paquete existente. Se elige ampliar a movimientos ZIP v6 para conservar CSV
original y mapeo junto con el libro y evitar otro tipo de ZIP. Los lectores v1–v5
siguen vigentes; consolidación permanece independiente. Esta es una decisión de
implementación dentro del alcance ya autorizado.

## Transformaciones admitidas

CSV hasta 2 MB, 20,000 registros, 40 columnas y 2,000 caracteres por celda.
Separador coma, punto y coma o tabulador; codificación UTF-8 con BOM opcional o
Windows-1252 elegida explícitamente. Cabeceras vacías/repetidas, filas irregulares,
comillas incompletas y bytes ilegibles se rechazan con motivo controlado.

Cada campo de COLUMNS usa columna, valor declarado, pendiente o ID técnico por
fila (sólo ID). Fechas ISO, día/mes/año o mes/día/año se eligen explícitamente.
Números se convierten con Decimal y agrupación estricta, sin redondear. Magnitud
es una transformación explícita para cantidad, importe, comisión e impuesto;
los originales permanecen íntegros. No admite expresiones ejecutables ni fórmulas.
Campos numéricos vacíos permanecen pendientes; los ceros deben venir del CSV o
de una declaración. UNKNOWN conserva el momento desconocido.

Los valores de Tipo/Moneda/MomentoFlujo se corresponden explícitamente con los
enumerados del libro. Coincidencias canónicas pueden proponerse; no aprueban
evidencia. Fechas futuras de operación, secuencias incompatibles, pares FX y
reportos se comprueban con Event/read_ledger/book_at. Una misma columna puede
elegirse deliberadamente para varios campos; se advierte sobre fecha/liquidación.

Duplicados económicos sin ID requieren decisiones de fila documentadas; IDs
repetidos bloquean. Excluir una fila exige motivo/fuente y nunca borra el original.
Máximo 100 decisiones explícitas. Una decisión de incluir no supera otros errores.
Todos los registros deben resolverse antes de usar el libro. Puede guardarse un
borrador incompleto y conservar sus pendientes. No se generan asientos de apertura.

## Estado, procedencia y continuidad

La edición es una propuesta separada del libro vigente; navegar o cargar un
mapeo no lo sustituye. Guardar el borrador o usar el libro es una acción explícita
que reemplaza los CSV/borradores de Movimientos, con aviso de descargar el ZIP.
Retira resultados, confirmaciones y vínculos que ya no correspondan; conserva
las otras cuentas y el área de análisis. Cerrar el panel conserva la edición y
retira la confirmación de importación.

Un mapeo JSON v1 reutilizable contiene opciones y correspondencias, sin decisiones
de fila ni consentimientos; cabeceras distintas requieren nueva revisión. Al
aplicarlo a otro archivo se renueva la fuente/motivo. El ZIP v6 conserva
mapping/source.csv y mapping/proposal.json, huellas, ámbito y vínculo por hash
con el libro cuando se aplicó. Máximo 100 KB para la propuesta y 15 MB para ZIP,
con límites internos y nombres permitidos. No se guardan PDF/XML, claves ni
aprobaciones. Cambios del motor no deben ejecutar módulos declarados en el ZIP.

La procedencia se reproduce desde bytes exactos, registro y líneas físicas del
CSV, configuración y decisiones. Los resultados no se serializan como aprobados.
El cifrado local existente debe admitir v6 además de v1–v5. Se añade también al
inventario el resumen TXT opcional que ya conserva el paquete.

## Auditoría

Pruebas independientes de dinero/cargos/pendientes, fechas ambiguas, decimales y
centavos, datos desconocidos, duplicados, fuentes cambiadas, archivos hostiles y
ZIP alterado. Ciclo guardar/cerrar/reabrir/reemplazar/vaciar y cifrado compatible.
Windows/Linux, Ruff, dependencias, contenedor, navegador, 1440/768/390, teclado,
axe y PDF/ZIP coherentes. Una revisión independiente antes de integrar y cotejo
publicado ficticio; usuario/teléfono físico y evidencia real se registran aparte.
