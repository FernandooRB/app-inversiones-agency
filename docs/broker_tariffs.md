# Perfil contractual de costos por intermediario

La aplicación acepta un CSV con **un solo perfil de costos para el análisis actual**. Permite
declarar la tarifa pública, contractual o negociada que se pretende aplicar a un cliente, sin
guardar su nombre ni número de cuenta. El perfil sustituye todos los campos manuales del bloque
de costos, requiere moneda base MXN y se conserva únicamente durante la sesión de Streamlit.
Una tarifa publicada no acredita la comisión efectiva de un cliente: la propuesta debe usar el
contrato, convenio, confirmación o estado de cuenta que corresponda a ese cliente, producto y fecha.
Si difieren, el acuerdo particular documentado y vigente prevalece sobre la guía pública **sólo**
para las operaciones y condiciones que cubra. No se escoge automáticamente la tasa más baja.

La plantilla contiene estas columnas, en este orden:

```csv
Intermediario,Producto,Mercado,TipoTarifa,VigenteDesde,VigenteHasta,FechaConsulta,ComisionOperacionPct,IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente
Casa de Bolsa,EDITAR_PRODUCTO,EDITAR_MERCADO,PUBLICA,AAAA-MM-DD,,AAAA-MM-DD,EDITAR,EDITAR,EDITAR,EDITAR,EDITAR,EDITAR,EDITAR_FUENTE
```

- `ComisionOperacionPct` es la comisión antes del IVA aplicable a cada compra o venta.
- `IVAPctComision` se aplica únicamente a esa comisión transaccional.
- `ComisionMinimaMXN` se cobra por cada orden no nula.
- `CostoMercadoPbSupuesto` es una estimación del equipo para spread, deslizamiento e impacto; no
  debe presentarse como comisión publicada por la institución.
- `CostoFijoAnualTotalMXN` reúne los cargos recurrentes fijos del año **después** de los impuestos
  aplicables, por ejemplo plataforma, market data o cuenta.
- `AdministracionAnualTotalPct` es la tasa anual recurrente total sobre el saldo, también después
  de impuestos aplicables.
- `TipoTarifa` es `PUBLICA`, `CONTRACTUAL` o `NEGOCIADA_CLIENTE`. Es una declaración del equipo,
  no una autenticación del acuerdo. Para una comisión especial, selecciona `NEGOCIADA_CLIENTE` y
  conserva el convenio o confirmación en el expediente privado; no pongas datos personales en el CSV.
- `VigenteDesde` y `VigenteHasta` delimitan la aplicación de la tasa. `VigenteHasta` puede quedar
  vacío si el documento no establece una fecha final. La app rechaza un perfil fuera de vigencia
  en la fecha del análisis. Una vigencia declarada no verifica por sí sola que el cliente cumpla
  las condiciones del convenio o de un tramo por volumen.
- `FechaConsulta` no puede estar en el futuro. `Fuente` identifica el contrato, guía, estado de
  cuenta o página utilizada mediante una referencia no identificante.

La plantilla anterior de 11 columnas se acepta para reproducir escenarios existentes, pero queda
etiquetada `SIN_ALCANCE` y no acredita la tarifa particular de un cliente. Los perfiles `PUBLICA`
y `SIN_ALCANCE` muestran una advertencia en la app. El PDF conserva tipo, vigencia, referencia y
huella del CSV para que una persona pueda revisar el supuesto utilizado.
La plantilla descargable trae campos `EDITAR` para que un archivo sin completar no sea interpretado
como una tarifa real.

El reporte mantiene separados el costo inicial de las órdenes y el costo recurrente anual. También
muestra un costo estimado del primer año. Ninguno se descuenta de los retornos, del riesgo ni de los
pesos objetivo. La estimación no modela escalones calculados con promedios móviles, promociones,
fondos con gastos incorporados en su valor, penalizaciones, tipo de cambio operativo, impuestos sobre
ganancias, retenciones, lotes o profundidad real. Un perfil aplica la misma comisión transaccional a
todos los activos del análisis; si el contrato cambia por instrumento o mercado, este perfil **no
representa la cartera completa**. En ese caso usa las reglas por orden del bloque siguiente y
comprueba que cada activo y dirección estimada estén cubiertos. No promedies tasas ni apliques una
tarifa especial de un cliente a otro.

## Reglas por orden

El importador `read_order_tariffs_csv` lee un archivo separado con reglas de compra, venta o ambas
para cada activo del análisis. Requiere exactamente estas columnas y un máximo de 200 filas y
100 KB; la plantilla siguiente contiene marcadores que deben sustituirse antes de usarla:

```csv
Activo,Intermediario,Producto,Mercado,Operacion,TipoTarifa,VigenteDesde,VigenteHasta,FechaConsulta,ComisionOperacionPct,IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,Fuente
EDITAR_ACTIVO,EDITAR_INTERMEDIARIO,EDITAR_PRODUCTO,EDITAR_MERCADO,AMBAS,NEGOCIADA_CLIENTE,AAAA-MM-DD,,AAAA-MM-DD,EDITAR,EDITAR,EDITAR,EDITAR,EDITAR_FUENTE
```

`Activo` debe coincidir exactamente con un instrumento del análisis. `Operacion` admite `COMPRA`,
`VENTA` o `AMBAS`. Dos filas no pueden cubrir el mismo activo y lado, incluso si una dice `AMBAS`.
Las cuatro cifras son obligatorias, aunque su valor sea cero. La comisión se expresa en porcentaje,
el IVA como porcentaje de la comisión, el mínimo en MXN y el costo de mercado en puntos base. La
vigencia debe cubrir la fecha del análisis y la fuente no puede haberse consultado después de ella.
El estimador rechaza una orden sin regla; nunca sustituye silenciosamente una tarifa faltante por
la tasa general. Conserva el intermediario, producto, mercado, fuente y tarifa aplicada en cada fila
del cálculo.

El CSV identifica un supuesto, no acredita un convenio ni la elegibilidad por volumen. No agregues
nombres, cuentas ni otros datos personales. La interfaz ofrece una carga distinta del perfil general:
ambas opciones son excluyentes y las cuatro tasas transaccionales manuales deben quedar en cero.
El [manifiesto de alcance de una cuenta](account_scope.md) es obligatorio con estas reglas; ata
por huella los archivos de cartera y tarifas y rechaza intermediarios mezclados. Para una cartera
real se requiere el CSV valuado de esa cuenta, no pesos manuales.
Los cargos anuales se declaran una vez en los campos manuales con su referencia. El detalle CSV de
costos y ambos PDF muestran la fuente, tasas, vigencia e importes de cada orden y reconcilian el
desglose con el resumen. Si falta cobertura para alguna orden del análisis, no se genera reporte.
Si el mismo instrumento está en dos cuentas con condiciones distintas, la cartera agregada por
símbolo tampoco separa esas órdenes. Prepara un reporte por cuenta; el consolidado queda pendiente.

## Revisión de fuentes públicas

### GBM: tabla general confirmada para el piloto propio

El titular confirmó el 30 de septiembre de 2026 que la tabla de la ayuda de GBM es la referencia
general que quiere usar. La [FAQ oficial de GBM](https://gbm.com/faqs/que-comisiones-cobran-al-invertir-en-gbm)
publica: Smart Cash sin comisión; Smart Cash Dólares con 1.5 % anual más IVA descontado a diario;
corretaje de fondos de renta variable en Trading MX y portafolios recomendados según monto operado
promedio de los últimos tres meses; y fondos de deuda sin comisión de corretaje. Los cinco tramos
de ese corretaje son **0.25 % hasta 1 millón MXN, 0.20 % de 1,000,001 a 3 millones, 0.15 % de
3,000,001 a 5 millones, 0.125 % de 5,000,001 a 10 millones y 0.10 % por encima de 10 millones**.
La FAQ también indica un arancel anual más IVA para cada portafolio recomendado, consultable en
su ficha, y un arancel anual de fondos que la FAQ resume como 1 % a 2.75 %, pero cuya cifra
aplicable depende de la serie y tipo de titular y debe consultarse en el DICI. Estos cargos
diarios no se deben transformar en corretaje por operación.

Para la cartera BMV propia, **22 de 22 comisiones de compraventa visibles** coincidieron al
centavo con 0.25 % del nominal calculado. Los cargos históricos se toman del estado; para
escenarios internos se puede declarar 0.25 % como **tasa observada en esta cartera**, con producto,
fecha y fuente explícitos. Ese número coincide con el primer tramo de la FAQ, pero la redacción
de la FAQ no prueba automáticamente que esa tasa
rija cada acción, ETF, FIBRA o título SIC, ni define cómo tratar promedios fraccionarios en los
límites. El software no selecciona el tramo sin el promedio de tres meses y su convención.
Las tarifas particulares de futuros clientes pueden diferir; se aplican sólo a las órdenes
que cubran. Un fondo o portafolio necesita su serie/ficha y revisión de si los rendimientos
utilizados ya incorporan cargos diarios para evitar doble conteo. El IVA de corretaje de una
orden se registra según el cargo o documento aplicable; la FAQ no fija por sí sola el importe
de IVA de cada operación de la cartera.

Estado de la revisión comparativa: 17 de septiembre de 2026; aclaración GBM: 30 de septiembre
de 2026. Estos hallazgos sirven para pedir y conciliar el
documento correcto; **no son perfiles precargados** porque las condiciones dependen del producto,
segmento, volumen, contrato y fecha.

| Institución | Evidencia pública revisada | Tratamiento en la aplicación |
| --- | --- | --- |
| GBM | Su página oficial separa costos por producto y muestra tramos dependientes del volumen para ciertos productos de Trading MX. | Capturar el producto y tramo que correspondan al contrato; no extrapolar entre Trading MX, USA, fondos o portafolios. |
| Bursanet / Actinver Trade | La página oficial publica tramos de 0.25% a 0.10% para operaciones de mercado de capitales y declara servicios administrativos sin costo. | Confirmar el tramo del periodo y si aplica a BMV/SIC y al contrato concreto. |
| Actinver asesorado | Su guía distingue Banco, Casa de Bolsa, gestión y servicio no asesorado, con cargos y bases diferentes. | Mantener perfiles separados por servicio; no reutilizar Actinver Trade para una cuenta asesorada. |
| Finamex Trading | La guía de enero de 2026 publica comisión por transacción, administración anual por saldo y cargo mensual de market data, más IVA. También describe mandatos cuyas comisiones se pactan con el cliente según monto, instrumentos y plazo. | Registrar componentes transaccionales y recurrentes por separado; para mandatos usar el acuerdo particular, no la tabla pública de Trading. |
| Kuspit | El sitio ofrece capitales, ETF, CETES y fondos; sus condiciones remiten a la guía y al contrato para comisiones. | No asignar una tasa sin obtener el documento vigente aplicable al cliente. |
| Finsus | Es una S.F.P. con productos de ahorro e inversión a plazo; su sitio remite al contrato para costos y comisiones. | Tratarlo como producto de liquidez o plazo con tasa, protección y contrato propios, no como tarifa de corretaje BMV/SIC. |

Fuentes oficiales consultadas:

- [GBM: comisiones por producto](https://gbm.com/faqs/que-comisiones-cobran-al-invertir-en-gbm)
- [Bursanet: beneficios y comisiones](https://www.bursanet.mx/beneficios.html)
- [Actinver: Guía de Servicios de Inversión](https://www.actinver.com/documents/d/actinver/guia-de-servicios-de-inversion)
- [Actinver Trade: beneficios y comisiones](https://actinvertrade.actinver.com/beneficios.html)
- [Finamex: Guía de Servicios de Inversión](https://www.finamex.com.mx/servicios-de-inversion/guia-de-servicios-de-inversion)
- [Kuspit: condiciones de servicio](https://kuspit.com/condiciones-servicio)
- [Finsus: inversión a plazo y contrato](https://web.finsus.mx/personas/inversiones)
