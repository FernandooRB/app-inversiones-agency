# Reserva fiscal ilustrativa por ventas

La aplicación puede estimar una reserva de revisión cuando existe una cartera actual valuada en MXN
y el equipo aporta el costo fiscal actualizado de cada instrumento. El cálculo se presenta separado
de rendimientos y costos; no modifica los pesos objetivo ni afirma determinar el impuesto definitivo.

El CSV contiene exactamente:

`FechaCorte,Instrumento,CostoFiscalActualizadoMXN,TratamientoFiscal,TasaEscenarioPct,Fuente`

- `FechaCorte` debe coincidir con la cartera actual.
- `Instrumento` debe cubrir exactamente el mismo universo.
- `CostoFiscalActualizadoMXN` debe provenir de una constancia o cálculo revisado; la app no actualiza
  inflación, reconstruye lotes ni valida comprobantes.
- `PF_ACCIONES_BOLSA_ART129` exige 10% y sólo debe elegirse después de confirmar que el valor y la
  operación cumplen el artículo 129 de la LISR.
- `ESCENARIO_TASA_DECLARADA` acepta de 0% a 100% para una reserva explícita cuya interpretación
  queda documentada por la fuente. No convierte una tasa corporativa o marginal en impuesto definitivo.
- `NO_ESTIMADO` deja la tasa vacía y conserva el nominal vendido como pendiente de clasificación.

Los [flujos fiscales documentados](tax_cash_flows.md) tienen un archivo y resumen propios; no se
combinan automáticamente con esta reserva de ventas.

Para cada venta, el motor asigna el costo fiscal en proporción al valor actual vendido, resta la
comisión de venta declarada del ingreso y separa ganancia y pérdida. La reserva aplica la tasa sólo a
la ganancia positiva de cada instrumento. Esta aproximación no compensa pérdidas entre emisoras,
intermediarios o ejercicios y puede ser conservadora. Tampoco calcula dividendos, intereses, tipo de
cambio fiscal, deducciones, acreditamientos, pagos provisionales o declaración anual.

## Referencias vigentes revisadas el 18 de septiembre de 2026

- [LISR, artículo 129](https://wwwmat.sat.gob.mx/articulo/59621/articulo-129): para personas físicas,
  ciertas ganancias por acciones e índices en bolsa están sujetas a 10% definitivo; la propia norma
  define cobertura, costo promedio, actualización, comisiones, pérdidas y obligaciones de información.
- [LISR, artículo 140](https://wwwmat.sat.gob.mx/articulo/32450/articulo-140): los dividendos de personas
  físicas tienen acumulación y, para distribuciones de personas morales mexicanas, una tasa adicional
  de 10%. Este módulo no los calcula.
- [LISR, artículo 135](https://wwwmat.sat.gob.mx/articulo/89366/articulo-135) y
  [LIF 2026](https://www.diputados.gob.mx/LeyesBiblio/pdf/LIF_2026.pdf): la retención anual sobre el
  capital que da lugar a intereses es un pago provisional; para 2026 la tasa general indicada por la
  LIF es 0.90%. No debe confundirse con ISR definitivo sobre rendimiento.
- [LISR, artículo 9](https://wwwmat.sat.gob.mx/articulo/93578/articulo-9): las personas morales aplican
  30% al resultado fiscal anual, después de las reglas correspondientes. El módulo no reconstruye ese
  resultado y por eso cualquier tasa corporativa sólo puede mostrarse como escenario declarado.

Las referencias pueden cambiar. Antes de un caso real deben revisarse el ejercicio fiscal, residencia,
tipo de contribuyente, instrumento, mercado, intermediario, constancias, pérdidas y situación completa
con una persona especialista en impuestos.
