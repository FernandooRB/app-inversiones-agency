# Identidad de instrumentos y mercado de la serie

El manifiesto opcional añade trazabilidad a los **tickers de precios** del análisis. Contiene una fila
por ticker y exactamente estas columnas:

`Instrumento,ISIN,MercadoNegociacion,SimboloNegociacion,MercadoSerie,MonedaSerie,TipoSerie,FechaVerificacion,Fuente`

No contiene posiciones, cuentas ni nombres de clientes. Su huella SHA-256 se muestra en la app y en la
descripción de fuente del PDF. No se guarda en una base de datos. Los preparadores de CETES, Bonos M,
liquidez y fondos necesitan su propia conciliación de emisión, vehículo o serie; no se incluyen en este
archivo de tickers de precios.

| Campo | Regla informática |
| --- | --- |
| `Instrumento` | Universo exacto, sin duplicados, de tickers de precios solicitados. |
| `ISIN` | 12 caracteres, patrón ISO 6166, dígito de control módulo 10 y sin duplicados en el análisis. El dígito válido no demuestra que el ISIN exista ni que corresponda al ticker. |
| `MercadoNegociacion` | `BMV`, `BIVA` o `SIC`; representa dónde se pretende negociar el valor. |
| `SimboloNegociacion` | Clave declarada del valor negociable; puede diferir del ticker de análisis. Debe contrastarse con el intermediario y la bolsa. |
| `MercadoSerie` | `BMV`, `BIVA`, `SIC` u `ORIGEN_EXTRANJERO`; representa de dónde proviene el precio analizado. |
| `MonedaSerie` | Coincide con la moneda de cotización declarada para ese ticker en la app. |
| `TipoSerie` | `CIERRE_LOCAL_AJUSTADO` exige igual mercado de negociación y de serie, con precio MXN. `PROXY_ORIGEN_AJUSTADO` exige negociación SIC y serie de origen extranjero; nunca equivale a precio local ejecutable. |
| `FechaVerificacion`, `Fuente` | Fecha válida no futura y referencia textual sin fórmulas CSV. |

La validación sólo comprueba estructura y consistencia declarada. Para el [piloto con datos reales](real_data_pilot.md)
hay que confirmar en una fuente autorizada el ISIN, la clave/serie exacta, el segmento de cotización,
la moneda y subunidad, el horario, eventos corporativos, ajustes, disponibilidad en la casa de bolsa y
derechos de uso. Dos archivos que repiten un ISIN incorrecto no se convierten en evidencia independiente.

La [BMV describe el SIC](https://www.bmv.com.mx/es/mercados/mercado-global) como una plataforma de
valores extranjeros con operación en pesos y distingue los
[cierres SIC como producto de datos](https://www.bmv.com.mx/es/productos-de-informacion/bases-de-datos).
La [descripción ISO del ISIN](https://committee.iso.org/sites/tc68/home/articles/content-left-area/articles/what-is-isin.html)
define su longitud y dígito de control. Estas fuentes no verifican el contenido de un manifiesto
concreto: esa comprobación se hace por instrumento y por fecha.
