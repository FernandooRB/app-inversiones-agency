# Guardar y retomar movimientos

En **Operación → Movimientos**, el apartado **Guardar revisión de movimientos**
permite descargar un ZIP incluso si todavía faltan datos o confirmaciones. Conserva
los CSV cargados, el corte del libro y la moneda elegida. Sirve para continuar una
revisión en el piloto gratuito, donde la sesión puede desaparecer.

Puede incluir el libro, controles de cierre, cotizaciones, FX del cierre, valores
de reportos, NAV histórico y FX de flujos. Se conservan los bytes originales:
el paquete no corrige centavos, completa valores vacíos ni clasifica transferencias.
No incluye PDF/XML de la pestaña Originales GBM, propuestas de implementación,
credenciales, el expediente completo ni resultados financieros archivados.

Para retomarlo, abre **Abrir paquete de movimientos**, carga el ZIP y pulsa
**Retomar movimientos**. Se reemplazan los insumos de esa revisión en la sesión,
se recuperan corte y moneda y se recalculan las vistas con el motor vigente.
Las confirmaciones de precios y flujos empiezan desmarcadas. Un cambio de insumos,
corte o moneda invalida las confirmaciones correspondientes y retira el resultado
anterior hasta que se revise de nuevo.

Retomar una revisión también exige renovar la confirmación de cantidades para
seguimiento, si está habilitado. Los [errores de insumos](operation_errors.md)
identifican la etapa afectada y permiten consultar las otras pestañas.

Cada archivo recuperado se identifica junto a su carga. Puede quitarse o
reemplazarse; quitar el reemplazo no hace reaparecer el archivo anterior. Quitar
el libro también retira el saldo que otras operaciones usan como referencia.

Un paquete vinculado a expediente y cuenta requiere ese mismo contexto. Un
paquete temporal se abre en revisión temporal; no se adjunta automáticamente a un
expediente. Abrirlo no escribe en almacenamiento permanente ni concede aprobación.

El ZIP contiene datos privados **sin cifrar**. Consérvalo con el mismo cuidado que
el documento original. La descarga no convierte la sesión de Community Cloud en
almacenamiento permanente ni contrata un servicio.

## Formato y validación

El formato `sig.operations.review`, versión 1, incluye `review.json` e insumos
permitidos bajo `inputs/`. El manifiesto registra fecha de descarga, corte, moneda,
cuenta si corresponde, tamaño y SHA-256 de cada CSV, huellas del motor y estado
`PENDING_REVIEW`. No admite confirmaciones, aprobaciones ni resultados guardados.
Las huellas del código normalizan finales de línea Windows/Linux; las de los CSV
siempre corresponden a sus bytes originales.

Se aceptan hasta siete CSV de 2 MB cada uno, un manifiesto de 32 KB y un ZIP de
15 MB. El servidor puede imponer un límite de carga menor. Se leen en memoria,
sin extraer rutas al disco; se rechazan rutas adicionales, duplicados, enlaces,
cifrado ZIP, compresión no admitida, tamaños excesivos y discrepancias de huellas.
La lectura acotada precede a los validadores financieros de cada pantalla.

Las huellas comprueban consistencia interna, no identidad del autor ni autenticidad
del estado de cuenta: quien modifica datos y manifiesto puede generar otro paquete
coherente. Un cambio de versión se informa y no bloquea recuperar los insumos.
Los valores incompletos siguen sujetos a los validadores y a la revisión financiera.

Este formato es distinto del [paquete de análisis por cuenta](account_workflow.md).
No se pueden intercambiar ambos ZIP. La lectura usa las capacidades documentadas de
[zipfile de Python](https://docs.python.org/3.12/library/zipfile.html), con límites
y lista de miembros definidos por la app, además del filtro visual de tipos de
[Streamlit](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader).
