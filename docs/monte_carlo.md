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
Al activar la simulación, el PDF comparativo añade una página con los supuestos,
la tabla final y una banda de percentiles; el CSV conserva los percentiles de
cada mes para auditoría interna.

## Flujos y costos

Se invierte el capital inicial en las proporciones elegidas. Cada escenario puede
tener aportaciones o retiros mensuales fijos, pero no ambos. Las aportaciones
nominales se agregan al final de cada mes con esas mismas proporciones. Para
cubrir un retiro se venden posiciones proporcionalmente; la venta bruta incluye
el costo por operación para que el retiro neto sea el solicitado. Si una
trayectoria no alcanza, se vende lo disponible, se registra el retiro parcialmente
cubierto y la cartera queda en cero, sin deuda ni posiciones negativas.
El costo por operación, expresado en puntos base del monto negociado, se descuenta
de la compra inicial, cada aportación, los retiros y el volumen comprado y vendido
al rebalancear.
La comisión anual se aplica como factor diario efectivo. El rebalanceo puede ser
nulo, trimestral, semestral o anual; la cartera deriva entre rebalanceos. El
valor real final divide el patrimonio nominal por `(1 + inflación anual)^años`.

En escenarios de aportaciones, «bajo capital aportado» es la proporción de
trayectorias cuyo valor nominal final es inferior a `capital inicial + aportaciones
nominales`. En escenarios de retiros, «con retiro no cubierto» es la proporción
de trayectorias en las que al menos un retiro planeado se pagó parcialmente o
no se pagó; también se muestra la mediana del monto efectivamente retirado.
Estas fracciones simuladas no son probabilidades calibradas del mundo real.
Los retiros son nominales fijos: no crecen con inflación. No se modelan
impuestos, spreads, custodia, liquidez, quiebra de intermediarios ni cambios de correlación.
Los retornos de entrada
deben ser diarios comparables; si falta FX en fechas de precios, la app no
ejecuta esta simulación.

Según [CFA Institute, Backtesting & Simulation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation),
el remuestreo histórico depende de que la historia represente riesgos futuros;
los modelos normales pueden omitir asimetrías y colas gruesas. El
[boletín de Investor.gov sobre desempeño](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)
recuerda que las proyecciones hipotéticas no son desempeño real.

## Siguientes controles

Agregar retiros crecientes con inflación y ampliar las
[pruebas de estrés](stress_testing.md) a escenarios nombrados por clase de activo,
comparaciones fuera de muestra y tratamiento de impuestos por instrumento y
régimen. Para CETES y bonos se necesita un modelo de flujos y valoración propio;
no se deben introducir rendimientos a vencimiento como si fueran retornos diarios.
