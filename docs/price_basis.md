# Base de precios para valuación y rendimiento

El precio que reproduce un estado de cuenta y la serie con la que se estima un
retorno pueden tener bases diferentes. Conocer símbolo, ISIN, mercado y moneda
no demuestra que dos columnas de cierre representen la misma magnitud.

## Qué hay que distinguir

| Dato | Uso | Comprobación necesaria |
| --- | --- | --- |
| Precio de valuación en la fecha | Cantidades × precio y patrimonio del libro | Reproduce la base de títulos y la convención del estado, con fecha y fuente |
| Cierre oficial de la bolsa | Referencia de cierre según su metodología | Verificar bolsa, serie, moneda y convención; puede diferir del último hecho |
| Serie ajustada por splits | Comparar precios expresados en una misma base de títulos | No confundir con el precio unitario impreso antes del evento |
| Serie ajustada por distribuciones | Modelo de retornos según su metodología | Revisar dividendos, splits, reinversión, fechas y cobertura de eventos |

El [glosario de BMV](https://www.bmv.com.mx/es/Grupo_BMV/Glosario) diferencia el cierre
ponderado del último hecho y contempla referencias alternativas cuando no existe
el primero. Una diferencia entre proveedores puede corresponder a convenciones
distintas; no basta con concluir que uno está equivocado.

## Yahoo: `auto_adjust=False` no acredita precios históricos sin reexpresar

La [tabla histórica de Yahoo](https://finance.yahoo.com/quote/API/history/) define
`Close` como ajustado por splits y distingue `Adj Close`, que incorpora además
dividendos o distribuciones. Su [ayuda de cierre ajustado](https://help.yahoo.com/kb/SLN28256.html)
describe esos ajustes. Pedir `auto_adjust=False` en yfinance conserva columnas
separadas; no deshace los ajustes que Yahoo ya aplicó a la serie recibida.

Por ejemplo, en un caso ficticio una acción puede valer 100 antes de un split
2 por 1 y aparecer como 50 en una historia reexpresada. Multiplicar ese 50 por
la cantidad histórica de un título daría 50, aunque el estado anterior al evento
mostraba 100. Es necesario conservar la base correcta de cantidades y precios.

El libro requiere precios compatibles con las cantidades de cada fecha. El modelo
de investigación usa su serie ajustada y la procedencia declarada. Sus columnas
no se intercambian sin comprobar ambas bases. El código conserva la confirmación
explícita de precios en el libro; un CSV numéricamente válido no acredita su base.

## Eventos y contraste entre fuentes

1. Conservar el precio original y su fuente; crear una comparación aparte.
2. Cotejar los cortes del estado con una referencia de la misma serie y fecha.
3. Revisar eventos corporativos antes de interpretar discrepancias históricas.
4. Distinguir fecha exderecho, fecha de pago y fecha de registro del intermediario.
5. Para dividendos en acciones, comprobar títulos y el tratamiento de fracciones.
6. Calcular rendimiento cuando el libro, los flujos y las valuaciones sean compatibles.

Un evento etiquetado por un proveedor como `Stock Splits` necesita contraste con
el aviso de la emisora. La etiqueta no decide por sí sola cómo registrar una
distribución en acciones o un pago de fracciones. Los importes de los originales
se mantienen y las excepciones conservan su revisión.

Las gráficas públicas de precios no acreditan por sí solas una metodología de
retorno total ni derechos de uso comercial. La [declaración de fuentes](data_sources.md)
y el [contraste de precios](real_data_pilot.md) conservan sus requisitos.
