# Cotejar fuentes de mercado

En **Operación → Fuentes y alertas → Cotejar precios, tipos de cambio y tasas**,
elige la práctica ficticia o carga dos CSV. Confirma el permiso de uso y documenta
el origen de cada observación. La versión publicada ofrece la práctica ficticia.
Para cotejar archivos autorizados, abre la aplicación local desde `localhost`
o `127.0.0.1`.

Elige un umbral en puntos base para precios, FX y tasas y pulsa **Cotejar
observaciones**. La vista muestra primero los valores fuera del umbral, las
convenciones que requieren revisión y las observaciones sin pareja. Usa el número
de observación para ver ambas fuentes y sus filas, aun cuando la tabla se limite
a las primeras 200. La cobertura cuenta por separado observaciones presentes en
ambos archivos y observaciones comparables.

## Cómo preparar archivos

Usa la plantilla descargable con encabezados exactos y valores en UTF-8. Cada
archivo admite 2 MB y 20,000 filas. Para cada observación declara:

| Campos | Qué registrar |
|---|---|
| `Tipo`, `Fecha`, `Serie` | `PRECIO`, `FX` o `TASA`. Fecha de observación `AAAA-MM-DD`. Usa en ambas fuentes el mismo identificador de la serie exacta que verificaste. El par FX se registra como `USD/MXN`. |
| `Mercado`, `Moneda` | Mercado o segmento declarado, y moneda `MXN` o `USD`. Dos listados o series distintos requieren identificadores distintos. |
| `Unidad` | `POR_TITULO` para precios, `MXN_POR_USD` o `USD_POR_MXN` para FX, `PORCENTAJE_ANUAL` para tasas. Usa la moneda que corresponde al numerador de la cotización FX. |
| `Metodo` | Describe la definición del dato. Por ejemplo, cierre ajustado o sin ajuste, spot o FIX a fecha de determinación, tasa de subasta o fecha de colocación. Usa la misma descripción sólo cuando las definiciones coincidan. |
| `Corte` | Instante documentado `AAAA-MM-DDThh:mm:ss-06:00` o `…Z`, en la fecha de observación declarada. Las zonas equivalentes se comparan por su instante. Si desconoces la hora, consigue la evidencia antes de cotejar esa fila. |
| `PlazoDias`, `BaseDias` | Para tasas, plazo en días y base anual 360 o 365. Para precios y FX, deja ambos vacíos. |
| `Valor` | Decimal sin símbolo de moneda, separadores de miles ni notación científica. `7.05` representa una tasa anual de 7.05%. |
| `Proveedor`, `Origen`, `Evidencia` | Quién entregó el archivo, quién generó el dato y dónde se puede cotejar. Una segunda distribución del mismo origen no aporta independencia. |

El cruce usa tipo, fecha y el identificador exacto de serie. Los mercados, monedas, unidades, métodos,
horas, plazos y bases que difieren dejan la fila por revisar y preservan ambos
valores. Un proveedor, origen o evidencia compartidos también requieren revisión.
Los marcadores como «N/D» o «sin dato» requieren completar el campo indicado.
No se rellenan fechas ni se invierte un par para hacerlos coincidir.
Los umbrales se evalúan antes de redondear la presentación:

- Precio y FX: `(principal − referencia) / referencia × 10,000` puntos base.
- Tasa anual: `(principal − referencia) × 100` puntos base cuando ambas tasas
  están expresadas como porcentaje. De 7.00% a 7.05% hay 5 puntos base.

Banxico distingue fechas de determinación, publicación y aplicación del FIX.
La Reserva Federal describe H.10 como tasas de compra de mediodía en Nueva York.
Estas referencias pueden corresponder al mismo día con cortes distintos.
[FIX de Banxico](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadroAnalitico&idCuadro=CF102&locale=es)
[Metodología H.10](https://www.federalreserve.gov/releases/h10/hist/)

El glosario de la BMV distingue el cierre de un precio ajustado por derechos
corporativos. Para CETES coteja el plazo y la fecha de referencia de la subasta
o colocación. [Glosario de la BMV](https://www.bmv.com.mx/es/Grupo_BMV/Glosario)
[Subastas y colocación de Banxico](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF107&locale=es&sector=7)

## Evidencia y continuidad

Descarga el JSON desde **Descargar evidencia del cotejo**. Contiene los valores
aportados, filas de origen, huellas de ambos archivos, umbrales y resultados
pendientes de revisión. Conserva ambos CSV para repetir el cotejo con los mismos
umbrales. Cambiar un archivo o umbral retira el resultado anterior. El panel de
cotejo tiene su propio botón de vaciado y se mantiene separado del libro. Un
cotejo por sí solo no autoriza una valuación, cambiaria, financiera o fiscal.
