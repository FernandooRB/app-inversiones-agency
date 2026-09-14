# Escenarios Monte Carlo de patrimonio

La aplicación incorpora dos formas de crear trayectorias hipotéticas para las
asignaciones históricas que ya calcula. El resultado es investigación interna;
no es un pronóstico, promesa de rendimiento ni asignación individualizada.

## Métodos

- **Bloques históricos**: toma al azar bloques contiguos de retornos diarios
  observados (21 sesiones por defecto) y los aplica conjuntamente a todos los
  activos. Conserva la dependencia transversal y, dentro de cada bloque, parte
  de la secuencia temporal observada. Reutiliza el régimen de la muestra; no
  inventa crisis, inflación ni cambios estructurales ausentes de ella.
- **Lognormal correlacionado**: estima media y covarianza de `log(1 + retorno)`
  diario y genera vectores normales correlacionados. Al exponenciarlos obtiene
  factores de crecimiento estrictamente positivos. Es un modelo paramétrico
  sensible a la estimación y puede subestimar colas y cambios de régimen.

Ambos usan 21 sesiones por mes y 252 por año. El número de trayectorias y la
semilla se muestran y son configurables. Los percentiles 5, 50 y 95 se calculan
**entre trayectorias en cada mes**; no son intervalos de confianza estadísticos
de un parámetro ni límites garantizados para una cartera real.

## Flujos y costos

Se invierte el capital inicial en las proporciones elegidas. Las aportaciones
nominales se agregan al final de cada mes con esas mismas proporciones. El costo
por operación, expresado en puntos base del monto negociado, se descuenta de la
compra inicial, cada aportación y del volumen comprado y vendido al rebalancear.
La comisión anual se aplica como factor diario efectivo. El rebalanceo puede ser
nulo, trimestral, semestral o anual; la cartera deriva entre rebalanceos. El
valor real final divide el patrimonio nominal por `(1 + inflación anual)^años`.

«Bajo capital aportado» es la proporción de trayectorias cuyo valor nominal
final es inferior a `capital inicial + aportaciones nominales`. Este indicador
incluye los costos modelados, pero no equivale a una probabilidad calibrada del
mundo real. No se modelan retiros, impuestos, spreads, custodia, liquidez,
quiebra de intermediarios ni cambios de correlación. Los retornos de entrada
deben ser diarios comparables; si falta FX en fechas de precios, la app no
ejecuta esta simulación.

Según [CFA Institute, Backtesting & Simulation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation),
el remuestreo histórico depende de que la historia represente riesgos futuros;
los modelos normales pueden omitir asimetrías y colas gruesas. El
[boletín de Investor.gov sobre desempeño](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)
recuerda que las proyecciones hipotéticas no son desempeño real.

## Siguientes controles

Agregar retiros y trayectorias de agotamiento, escenarios de estrés explícitos,
comparaciones fuera de muestra y tratamiento de impuestos por instrumento y
régimen. Para CETES y bonos se necesita un modelo de flujos y valoración propio;
no se deben introducir rendimientos a vencimiento como si fueran retornos diarios.
