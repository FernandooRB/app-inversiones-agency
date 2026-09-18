# Perfil contractual de costos por intermediario

La aplicación acepta un CSV con **un solo perfil contractual** para convertir los términos del
intermediario en supuestos auditables. El perfil sustituye todos los campos manuales del bloque de
costos, requiere moneda base MXN y se conserva únicamente durante la sesión de Streamlit.

La plantilla contiene estas columnas, en este orden:

```csv
Intermediario,Producto,Mercado,FechaConsulta,ComisionOperacionPct,IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente
Casa de Bolsa,Cuenta de ejemplo,Capitales MX y SIC,2026-01-15,0.25,16,0,8,0,0,Contrato o tarifario de ejemplo
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
- `FechaConsulta` no puede estar en el futuro. `Fuente` identifica el contrato, guía, estado de
  cuenta o página utilizada.

El reporte mantiene separados el costo inicial de las órdenes y el costo recurrente anual. También
muestra un costo estimado del primer año. Ninguno se descuenta de los retornos, del riesgo ni de los
pesos objetivo. La estimación no modela escalones calculados con promedios móviles, promociones,
fondos con gastos incorporados en su valor, penalizaciones, tipo de cambio operativo, impuestos sobre
ganancias, retenciones, lotes o profundidad real. Un perfil aplica la misma comisión transaccional a
todos los activos del análisis; si el contrato cambia por instrumento o mercado, prepara análisis
separados o usa el escenario más conservador y documenta esa decisión.

## Revisión de fuentes públicas

Estado de la revisión: 17 de septiembre de 2026. Estos hallazgos sirven para pedir y conciliar el
documento correcto; **no son perfiles precargados** porque las condiciones dependen del producto,
segmento, volumen, contrato y fecha.

| Institución | Evidencia pública revisada | Tratamiento en la aplicación |
| --- | --- | --- |
| GBM | Su página oficial separa costos por producto y muestra tramos dependientes del volumen para ciertos productos de Trading MX. | Capturar el producto y tramo que correspondan al contrato; no extrapolar entre Trading MX, USA, fondos o portafolios. |
| Bursanet / Actinver Trade | La página oficial publica tramos de 0.25% a 0.10% para operaciones de mercado de capitales y declara servicios administrativos sin costo. | Confirmar el tramo del periodo y si aplica a BMV/SIC y al contrato concreto. |
| Actinver asesorado | Su guía distingue Banco, Casa de Bolsa, gestión y servicio no asesorado, con cargos y bases diferentes. | Mantener perfiles separados por servicio; no reutilizar Actinver Trade para una cuenta asesorada. |
| Finamex Trading | La guía de enero de 2026 publica comisión por transacción, administración anual por saldo y cargo mensual de market data, más IVA. | Registrar componentes transaccionales y recurrentes por separado. |
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
