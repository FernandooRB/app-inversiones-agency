# Preparar movimientos desde otras columnas CSV

En **Operación → Movimientos → Preparar desde CSV con otras columnas** puedes
relacionar un archivo con el libro normalizado. La web usa exclusivamente datos
ficticios; los archivos y resultados reales GBM se revisan localmente. El alojamiento
continúa en el plan gratuito, sin almacenamiento permanente nuevo.

1. Carga el CSV original. Elige su separador y codificación; no se deducen del nombre.
2. Declara el formato de fechas, separador decimal y agrupación de miles.
   `02/03/2026` requiere elegir día/mes o mes/día. `1.234,56` requiere decimal coma
   y miles punto; una agrupación irregular queda pendiente.
3. Relaciona los 14 campos con columnas o valores acreditados. **Importe es bruto**;
   comisión e impuesto se declaran por separado. Una celda vacía no equivale a cero.
   El ID técnico por fila identifica evidencia; no crea movimientos de apertura.
4. Declara las correspondencias de clasificación, moneda y momento de flujo.
   Una descripción como «Abono» no determina por sí sola una aportación o traspaso.
   `UNKNOWN` conserva el momento desconocido, sin aprobar el TWR.
5. Coteja cada propuesta con el original. Las repeticiones económicas requieren
   una decisión de incluir o excluir con motivo y fuente. El original no se elimina.
6. **Guardar borrador de correspondencia** permite conservar pendientes en un ZIP.
   **Usar movimientos del CSV** requiere resolverlos y confirmar el cotejo. Ambas
   acciones reemplazan los CSV y borradores de esa revisión, con sus controles y
   valuaciones. Descarga primero la revisión anterior si necesitas conservarla.

La edición previa a esas acciones es una propuesta: no sustituye el libro vigente.
Al cambiar su correspondencia se retiran las decisiones de fila; una nueva fuente
retira también los valores y confirmaciones anteriores. Cerrar el panel conserva
la edición y renueva la confirmación de importación.

Puedes descargar una correspondencia JSON para reutilizar columnas. No incluye
decisiones de fila ni confirmaciones. Otro archivo con las mismas cabeceras exige
declarar de nuevo la fuente y el motivo; cabeceras diferentes requieren otro mapeo.
No se ejecutan expresiones, fórmulas ni módulos declarados en los archivos.

## Qué conserva el ZIP v6

`mapping/source.csv` conserva los bytes originales. `mapping/proposal.json`
conserva correspondencias, decisiones, ámbito y huellas. Si se utilizó el libro,
su huella debe corresponder a la proyección del CSV. Los resultados y consentimientos
no se recuperan como aprobados. La reapertura valida integridad y requiere otra
revisión con el motor actual. Cambiar el motor no impide recuperar los insumos.

Los lectores de movimientos v1–v5 y consolidación v1 siguen disponibles. Las copias
cifradas locales admiten también v6. Los originales PDF/XML permanecen fuera del
ZIP; el CSV original **sí está dentro** y puede contener datos privados. El ZIP se
guarda sin cifrar hasta usar la herramienta local de copias personales.

Límites: CSV y libro normalizado hasta 2 MB, 20,000 registros, 40 columnas y 2,000
caracteres por celda; propuesta JSON hasta 100 KB, hasta 100 decisiones y ZIP hasta
15 MB. No se redondean importes ni se crean ceros, contrapartes, aperturas o fechas
para superar las validaciones. La transformación explícita de magnitud conserva
el signo original como evidencia y no clasifica reversos o reintegros.

## Práctica

Descarga el CSV y la correspondencia ficticios del panel. Carga ambos y aplica la
correspondencia. La apertura de 100 MXN, aportación de 50 y comisión de 1 producen
149 MXN de efectivo. Aportar 50 no equivale a ganar 50. Descarga el ZIP y vuelve a
abrirlo como archivo completo, sin extraer los JSON. Confirma otra vez las fuentes.

La emulación a 390 px no acredita una prueba física. La comprensión del nuevo
recorrido y su uso en Samsung S23 con Chrome requieren comprobación humana propia
de esta entrega; los reportes anteriores del usuario corresponden a versiones previas.
