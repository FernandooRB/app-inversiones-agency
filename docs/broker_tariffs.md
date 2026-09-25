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
representa la cartera completa**. Prepara análisis separados o usa un supuesto explícitamente
conservador y documenta la limitación hasta implementar reglas por orden. No promedies tasas ni
apliques una tarifa especial de un cliente a otro.

## Revisión de fuentes públicas

Estado de la revisión: 17 de septiembre de 2026. Estos hallazgos sirven para pedir y conciliar el
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
