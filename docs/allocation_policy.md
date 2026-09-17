# Política de asignación por clase de activo

La aplicación permite declarar una clase para cada ticker y fijar un intervalo mínimo y máximo para
cada clase. La clasificación es un dato de entrada del usuario: el motor no la infiere del nombre del
ticker ni la valida contra un proveedor. Cuando se añade una serie CETES preparada, la aplicación la
clasifica como `deuda_gubernamental`.

El formato de cada regla es una línea CSV:

```text
renta_variable,20,60
deuda_gubernamental,40,80
```

Los porcentajes se aplican al peso total de todos los instrumentos de la clase. Cada activo debe
pertenecer exactamente a una clase y cada clase utilizada debe tener una regla. Además del intervalo
por clase, sigue vigente el peso máximo individual.

Antes de optimizar se comprueba que:

- los mínimos y máximos estén entre 0 % y 100 % y que mínimo no exceda máximo;
- ninguna clase exija más peso del que admiten sus activos bajo el límite individual;
- la suma de mínimos no exceda 100 % y los máximos permitan llegar a 100 %;
- todas las clases formen una partición completa de los activos.

Máximo Sharpe, mínima volatilidad y la frontera eficiente usan las mismas restricciones. La nube de
carteras también respeta los intervalos, aunque continúa siendo una muestra visual y no uniforme. Las
pruebas de corte único, cuatro cortes, revisiones sucesivas y sensibilidad vuelven a aplicar la misma
política en cada estimación.

Si pesos iguales incumple la política, se sustituye por la **referencia simple factible**: la cartera
permitida más cercana a pesos iguales en distancia cuadrática. La cartera actual sigue siendo una
referencia observada y puede quedar fuera de la política; no se modifica automáticamente.

La política y el número de activos declarados en cada clase aparecen en la app y en ambos PDF. Estos
límites describen un escenario de investigación. No determinan por sí solos la idoneidad para una
persona, no equivalen a un perfil de riesgo y no sustituyen la revisión de objetivos, horizonte,
liquidez, capacidad de pérdida, fiscalidad y restricciones contractuales.
