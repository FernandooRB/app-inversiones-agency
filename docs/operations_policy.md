# Política y avisos de cartera

Punto17: revisar un corte frente a criterios que declares. Está en **Operación →
Movimientos → Política y avisos de cartera**. Funciona en sesión temporal gratuita;
no exige activar el servicio de fuentes programadas ni almacenamiento permanente.

## Uso

1. Revisa el libro, precios sin ajuste, FX y valor de reportos del cierre.
2. Abre el panel de política y declara fuente y fecha de vigencia.
3. Elige la base de los pesos: patrimonio neto (incluye efectivo, pendientes y
   reportos valuados) o sólo instrumentos cotizados (excluye esos saldos).
4. Completa los criterios que quieras comprobar. Los números empiezan vacíos:
   tolerancia de desvío en puntos porcentuales, máximo individual en % de la base
   elegida y mínimo de efectivo disponible en % del patrimonio neto.
5. Declara objetivos en CSV `Instrumento,Moneda,PesoObjetivo`, con pesos en %.
   Un instrumento sin objetivo queda pendiente; no se supone objetivo cero.
6. Confirma política, cuenta y fuentes. Revisa cada dato, límite, fecha, motivo y
   fuente. No se crean órdenes, asientos ni cambios automáticos en la cartera.

Si tienes un análisis vigente de la misma cuenta/identidad/corte/universo, puedes
copiar una alternativa como propuesta. Conserva la procedencia del análisis y usa
base de instrumentos cotizados, sin convertir sus pesos a patrimonio total. Copiar
no confirma; editar los pesos, moneda o base retira la vinculación que deje de
corresponder. Una referencia posterior al corte no se aplica retroactivamente.

## Cálculos

- Desvío = peso observado − objetivo. Hay aviso cuando su valor absoluto excede
  la tolerancia declarada; la igualdad está dentro. No se añade un margen que
  pueda ocultar centavos, incluso para objetivos importados del análisis.
- Concentración = mayor peso individual de los instrumentos cotizados, bajo la
  base elegida. No es concentración por emisor o exposición subyacente: no se
  infieren esos datos de nombres/tickers.
- Efectivo disponible = efectivo liquidado menos **todos los pagos pendientes**,
  convertido al FX documentado del corte. Los cobros pendientes no financian el
  mínimo. Su porcentaje siempre utiliza patrimonio neto positivo.
- Falta de confirmación, datos de valuación, FX, reporto, denominador positivo,
  criterio u objetivo, o política/referencia todavía no vigente: pendiente. No se
  convierte un pendiente en cero ni se presenta como cumplimiento.

Ejemplo ficticio independiente: seis títulos a10 y efectivo40 dan patrimonio100.
Con objetivo60%, tolerancia5pp, máximo50% y mínimo de efectivo20%, hay un desvío
de concentración (60%>50%); los otros dos criterios están dentro. Otro caso:
liquidado90, pago pendiente80 y cobro pendiente100 no equivalen a disponible110;
disponible10 sobre patrimonio250 es4%.

Los importes originales no se ajustan. Los CSV/TXT conservan precisión; las tablas
y el PDF redondean sólo para presentación. Las diferencias pequeñas siguen en los
datos exportados.

## Continuidad y reportes

El **ZIP v5** incluye política propuesta, libro/CSV disponibles y, cuando existen,
borrador y propuesta anteriores. Reabrir recupera criterios como propuestas;
requiere confirmar de nuevo y evaluar con los datos del corte. No restaura
autorizaciones ni convierte resultados históricos del TXT en una evaluación vigente.
Los ZIP v1–v4 siguen legibles y conservan sus contratos históricos.

Editar una fuente, criterio, fecha, base o datos del corte retira confirmación.
Cerrar el panel retira los avisos de la ejecución actual, pero conserva la política
propuesta en el ZIP. Un error de evaluación no elimina el libro. Vaciar la revisión
retira su política y memoria, preservando las demás cuentas y herramientas.

CSV, TXT y PDF se derivan del mismo snapshot. El PDF conserva dos páginas y muestra
los avisos principales; el CSV/TXT contienen el detalle. Descarga el ZIP para
continuar. El JSON de política es una copia de los criterios; la reapertura dentro
de esta entrega se realiza mediante el ZIP.

Política: JSON esquema1 acotado a100KB, hasta100 objetivos, fuente500 caracteres y
cuenta/moneda explícitas. Evaluación: hasta500 posiciones. Se validan estructura,
decimales finitos, fechas, duplicados y ámbito de cuenta. El ZIP comprueba tamaños,
huellas y lista permitida antes de usar el contenido. Las huellas verifican integridad,
no autoría ni veracidad documental. Los archivos son privados y sin cifrar; no
incluyen originales PDF/XML ni secretos. Los identificadores originales se conservan
al editar/reabrir, y el CSV descargable neutraliza fórmulas de hoja de cálculo.

## Auditoría y pendientes

Pruebas nuevas reproducibles: `pytest tests/test_operations_policy.py` y
`SIG_POLICY_ONLY=1 node scripts/check_operations_browser.cjs`, además de la regresión
completa. El informe de entrega registra Windows/Linux, contenedor, navegador,
dependencias, diseño/accesibilidad, rendimiento, reportes, continuidad y publicación.

La prueba humana de la nueva pantalla y el teléfono físico se registran aparte.
Los autoinformes anteriores del Samsung S23/Chrome no prueban esta entrega. Siguen
pendientes la evidencia real de julio, reporto, transferencias, GMéxico y tarifas.
El alojamiento sigue en USD0 y los originales/resultados reales se revisan localmente.
