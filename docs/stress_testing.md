# Pruebas de estrés de cartera

La aplicación compara dos tipos de estrés. Se presentan por separado porque
responden preguntas distintas y ninguno establece una pérdida máxima posible.

## Peores ventanas históricas

Para cada alternativa de cartera se calcula el retorno diario como el producto
de los retornos de los activos y sus pesos. Esto supone que los pesos se restauran
al cierre de cada sesión. Después se componen los retornos en ventanas móviles de
1, 5 y 21 sesiones y se reporta la ventana con menor rendimiento, incluyendo sus
fechas de inicio y fin.

Este ejercicio conserva los movimientos conjuntos que sí aparecen en la muestra,
pero depende del periodo elegido, de los instrumentos que sobrevivieron hasta hoy
y de la calidad y sincronización de precios y tipos de cambio. Un evento futuro
puede ser peor o presentar relaciones distintas entre activos.

## Shock hipotético simultáneo

El usuario ingresa un cambio porcentual de precio por activo, en el mismo orden
de los tickers. El cambio de la cartera es la suma de `peso × shock`; el valor
estresado es `capital × (1 + cambio de cartera)`. También se muestra la
contribución de cada activo al cambio total. Cada shock debe ser al menos -100 %.

Es un cálculo estático de un paso sobre las posiciones valuadas en moneda base.
No se asigna probabilidad, duración o trayectoria de recuperación. Tampoco se
modelan ventas forzadas, impacto de mercado, falta de liquidez, suspensiones,
incumplimientos, margin calls ni un shock cambiario separado del precio convertido.
Por ello conviene definir escenarios con una historia económica coherente y
documentar por qué se eligió cada cambio, en lugar de interpretar los valores
predeterminados como una predicción.

La guía de [CFA Institute sobre backtesting y simulación](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation)
señala que las series financieras presentan colas gruesas, dependencia extrema y
cambios estructurales, y recomienda complementar la simulación con escenarios y
sensibilidad. El [boletín de Investor.gov sobre desempeño](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)
explica que resultados hipotéticos y retrospectivos no equivalen a desempeño real.

## Controles siguientes

Crear escenarios nombrados para México y SIC después de contar con un catálogo
de instrumentos que identifique clase de activo, moneda, duración, liquidez y
mercado. Validar por separado shocks de tasas para CETES y bonos mediante un
modelo de flujos y duración; no tratarlos como simples cambios de precio arbitrarios.
