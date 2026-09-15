# Revisión heurística de precios

Antes de convertir precios a la moneda base o incorporar la serie CETES, la aplicación revisa los
cierres originales de cada ticker en su moneda de cotización. Señala movimientos absolutos de 30 %
o más entre dos sesiones consecutivas y tramos de cinco o más sesiones consecutivas con el mismo
cierre exacto. Usa sólo observaciones dentro del periodo analizado. Las alertas muestran activo,
tipo, primera y última fecha, y magnitud o duración. La app permite descargar el listado completo
en CSV; el comparativo PDF resume hasta dos alertas y el total, mientras que el reporte
metodológico PDF muestra hasta 12 alertas y el total.

Los umbrales son controles operativos elegidos para invitar a revisar eventos corporativos,
calendario, disponibilidad de negociación y la fuente. Un salto puede ser real y un precio estable
puede ser correcto. La ausencia de alertas no verifica el ajuste por dividendos o splits, la moneda,
la integridad de la serie ni sus derechos de uso. No se corrigen, rellenan ni excluyen observaciones
automáticamente. En particular, un salto producido sólo por FX no aparecerá en esta revisión de
precios originales; la conversión cambiaria requiere comprobaciones separadas.
