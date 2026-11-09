# Reportos en el libro de movimientos

El libro admite reportos desde la perspectiva de quien invierte efectivo, en MXN o
USD, con apertura y vencimiento total documentados. Se cargan mediante el CSV
normalizado de **Operación → Movimientos**. La lectura de un PDF GBM sigue produciendo
evidencia para revisar; no convierte sus candidatos en movimientos aprobados.

Banco de México describe el reporto como la entrega de una suma a cambio de títulos,
con devolución de títulos de la misma especie contra el reembolso del precio más
un premio. Esa separación entre capital y premio orienta el sublibro.
[Fuente: Banco de México, operaciones de reporto](https://www.banxico.org.mx/elib/mercado-valores-gub/oebps/text/iv.html).

## Registrar el ciclo

Todos los importes se conservan como Decimal, sin corregir centavos ni redondear
para forzar coincidencias. `Cantidad` y `Precio` van en cero: los títulos entregados
en el reporto no se suman también como una posición ordinaria. `Instrumento` puede
identificar el colateral como descripción, conservando la misma etiqueta en ambas patas.

| Tipo | `Importe` | `Interes` | Efectivo |
| --- | --- | --- | --- |
| `OPEN_REPO` | Capital de una operación previa al inicio del libro | 0 | Ninguno; no es una aportación ni una nueva inversión |
| `REPO_START` | Capital invertido | 0 | Débito del capital, comisión e impuesto declarados |
| `REPO_MATURITY` | Cobro bruto, capital más interés | Interés ya incluido en el bruto, incluso 0 si está documentado | Crédito del bruto menos comisión e impuesto |

El interés del vencimiento es un desglose, no un segundo abono. Por ejemplo, un
reporto ficticio de 1,000 que vence con bruto 1,010, interés 10, comisión 1 e impuesto 2
abona 1,007. El resultado neto de su ciclo es 7, antes de cualquier otro movimiento.
No debe cargarse otro `INTEREST` o `TAX` por esos mismos componentes.

Cada operación tiene una `Referencia` única y sólo una apertura y un vencimiento.
Dos operaciones con el mismo colateral o importe necesitan referencias diferentes.
El vencimiento exige igual moneda e instrumento y esta igualdad exacta:

```text
Importe del vencimiento - Interes = Importe de apertura
```

Si el documento presenta una diferencia, se conserva como excepción antes de
normalizar el movimiento. Un CFDI que respalda un cargo no crea otro débito por sí
mismo. Un vencimiento sin apertura se rechaza; para un reporto previo al periodo
hay que documentar su capital inicial mediante `OPEN_REPO`, sin inventarlo a partir
del cobro. El saldo inicial del mes siguiente es un control de continuidad.

## Operación y liquidación

El derecho de cobro se incorpora en la fecha de apertura. El efectivo usa
`Liquidacion`; antes de esa fecha, el débito figura como pendiente firmado. Al
vencer, se da de baja el derecho y se reconoce el cobro neto, pendiente hasta
liquidar. Así no se suman al mismo tiempo el capital vigente y el cobro completo.

`OPEN_REPO` tiene las dos fechas iguales al inicio del libro y no admite cargos.
Un vencimiento anterior a la liquidación de su apertura se rechaza. Las fechas de
un estado deben revisarse antes de asignarles esos papeles; la coincidencia de dos
días impresos no acredita por sí sola el resto de la clasificación.

## Valuar al cierre

La pantalla muestra el capital de los reportos vigentes por referencia y moneda.
Para incluirlos en patrimonio se necesita este archivo adicional:

```text
Fecha,Referencia,Moneda,Valor,Fuente
2026-01-01,SIM-REPO-1,MXN,1003.25,Estado ficticio de prueba
```

`Valor` es el valor total documentado del derecho al corte, con el devengo que
corresponda a esa fuente. No es un precio unitario del colateral. El libro no
calcula interés lineal, no anticipa el premio final y no usa el principal como
valor por defecto. Exige una fila positiva y única por reporto vigente, fecha
exacta del cierre, fuente declarada y FX explícito si difiere de la moneda base.
Sin esas valuaciones, el patrimonio al corte permanece pendiente.

## Alcance y revisión

No se infieren renovaciones: cada nueva inversión requiere otra referencia y sus
movimientos. Vencimientos parciales, cambios de moneda o capital, intereses
negativos, garantías adicionales y operaciones desde la perspectiva de quien se
financia necesitan otro tratamiento revisado. No se calculan tasas ni bases
fiscales a partir de las retenciones.

Estos movimientos son internos para el cálculo de rendimiento. TWR y XIRR siguen
necesitando [valuaciones y flujos externos conciliados](operations_9_16.md), con
sus fechas y supuestos. Conciliar los reportos no acredita por sí solo el
rendimiento de toda la cuenta ni resuelve otros eventos corporativos.
