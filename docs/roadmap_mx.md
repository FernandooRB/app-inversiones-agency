# Plan de desarrollo: análisis de carteras en MXN

## Alcance acordado

- Uso interno por el equipo para investigación cuantitativa y escenarios generales.
- El alcance actual no contempla operar como asesor en inversiones registrado ante la CNBV.
  La salida para terceros se limita, por ahora, a material general y educativo, sujeto a
  revisión legal y a las autorizaciones laborales aplicables.
- La visión de producto incluye análisis de cartera y perfil de cada cliente con asignaciones
  individualizadas. Esa capacidad se mantiene como diseño futuro y no como entrega comercial
  habilitada mientras falte una ruta regulatoria y laboral confirmada.
- Clientes personas físicas y morales en México; instrumentos de mercados mexicanos y del SIC.
- Presupuesto recurrente inicial para datos y alojamiento: menos de MXN 1,000 al mes.
- Primera entrega: comparativo histórico en MXN para un caso ficticio, sin expedientes reales.
- Intermediarios prioritarios para investigar costos e importación: GBM, Actinver, Bursanet,
  Finamex y Kuspit. Finsus requiere evaluar por separado sus productos y disponibilidad de datos.
- Canal previsto de contratación: [stochasticsinvestmentgroup.com](https://stochasticsinvestmentgroup.com/).
  El formulario público sirve para primer contacto y cotización; no se conecta todavía con
  la app, no recibe posiciones detalladas ni dispara reportes automáticamente. El flujo
  pendiente es contacto, definición de alcance, contratación, recepción segura de datos,
  análisis interno, revisión humana y entrega versionada del PDF.

## Etapas y criterios de aceptación

| Etapa | Entrega | Criterio de aceptación |
| --- | --- | --- |
| 1. Comparativo | Máximo Sharpe, mínima volatilidad, pesos iguales y [cartera actual opcional](current_holdings_import.md) en un PDF | Mismos activos, fechas, moneda y supuestos; conciliación exacta del universo; pesos válidos; PDF legible; pruebas automatizadas |
| 2. Datos mexicanos | [Catálogo piloto](instrument_catalog.md), [ruta de precios CSV aportados](price_upload.md), [manifiesto y matriz de fuentes](data_sources.md), [revisión heurística](price_quality.md), serie FX independiente y referencias de tasas | Estructura, manifiesto, vigencia, alcance, huellas y alertas disponibles; el contrato, moneda, horario, ajustes y datos todavía necesitan comprobación humana; sin retornos diarios falsos por huecos |
| 3. Instrumentos | Acciones/ETF mexicanos y SIC; CETES, [Bonos M](bonos_m_adapter.md), [liquidez MXN](liquidity_adapter.md) y [fondos MXN](fund_adapter.md) preparados por archivo | Valoración y flujos apropiados por tipo; no tratar tasas como retornos diarios; validar externamente precios, devengado, cupones, tasas, valores de acción y distribuciones |
| 4. Optimización | Objetivos, límites, [benchmark independiente](benchmarking.md), [política por clase](allocation_policy.md), [atribución de riesgo](risk_attribution.md), [Black-Litterman](black_litterman.md), [sensibilidad histórica](allocation_sensitivity.md) y [covarianza diagonal fija o calibrada](covariance_shrinkage.md) | Restricciones individuales y por clase factibles; comparación con alternativa simple y benchmark en fechas comunes; contribuciones de volatilidad reconciliadas; escenario de retornos implícitos y opiniones trazables; falta validarlo en más regímenes y universos; asignación por perfil solo después de resolver las condiciones legales y laborales |
| 5. Simulación | [Trayectorias Monte Carlo](monte_carlo.md) y [pruebas de estrés](stress_testing.md) históricas/manuales en app y PDF | Supuestos visibles; resultados hipotéticos; trayectorias sin patrimonio negativo; shocks nombrados por activo o clase declarada; tasas y duración de deuda aún requieren modelos propios |
| 6. Validación | [Fecha de corte y revisiones sucesivas](backtesting.md), [cuatro cortes predefinidos](multi_cut_validation.md), referencias, [perfil contractual](broker_tariffs.md), [costo explícito de implementación](implementation_costs.md) y [reserva fiscal de ventas](tax_reserve.md) | Fechas de estimación/evaluación separadas; rebalanceos de 3, 6 o 12 meses sin datos futuros; sensibilidad al corte sin promediar evaluaciones solapadas; costos iniciales y recurrentes separados; costo fiscal actualizado aportado y ventas sin clasificar visibles; límites y fallos comunicados |
| 7. Datos de clientes | Etapa condicionada a la definición legal del servicio | No guardar perfiles, carteras identificables ni historial de propuestas para clientes hasta definir finalidad, privacidad, autorización laboral y alcance regulatorio |

## Decisiones metodológicas iniciales

- Optimización inicial de posiciones largas sin apalancamiento; límites por activo configurables.
- Índices como referencias; la inversión en un índice se representa con un vehículo identificable.
- El comparativo de la etapa 1 es histórico. No incluye comisiones, impuestos ni una recomendación
  personalizada. La cartera actual es una referencia ingresada por el usuario y no tiene que cumplir
  el límite de concentración de las carteras optimizadas.
- No se mezcla automáticamente la cotización local en MXN de un valor SIC con una conversión USD/MXN:
  el catálogo debe registrar mercado, moneda de cotización y exposición económica.
- La certificación AMIB es distinta de la inscripción en el Registro de Asesores en Inversiones
  de la CNBV. El alcance actual no incluye esa inscripción. Por tanto, no se habilita la entrega
  a clientes de recomendaciones de compra/venta, porcentajes objetivo o rebalanceos
  individualizados, ni administración o ejecución por cuenta de terceros. Un PDF
  sobre una cartera real o un perfil individual necesita revisión jurídica de su contenido y contexto;
  llamarlo «educativo» no modifica por sí solo la naturaleza del servicio.
- Antes de utilizar el proyecto como actividad externa, obtener las evaluaciones y autorizaciones
  laborales que correspondan. Las reglas concretas dependen del empleador y del puesto.
- Los impuestos se presentan por separado después de definir instrumento, intermediario y régimen
  fiscal del cliente; no se aplica una tasa universal.
- El [contraste H.10 completo](fx_reference_validation_2024h1.md) de AAPL/MSFT para
  enero-junio de 2024 muestra sensibilidad material de las métricas a la fuente FX.
  No determina todavía la fuente principal de producción ni valida precios de acciones.

## Fuentes a evaluar

- [CNBV: Registro de Asesores en Inversiones](https://www.gob.mx/cnbv/acciones-y-programas/registro-de-asesores-en-inversiones-rai).
- [Ley del Mercado de Valores, artículo 225](https://www.diputados.gob.mx/LeyesBiblio/pdf/LMV.pdf).
- [Banco de México: convenciones del FIX](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF85).
- [Banco de México: series de CETES](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF107).
- [SAT: enajenación de acciones](https://wwwmat.sat.gob.mx/articulo/59621/articulo-129).
- [yfinance: condiciones de uso de datos Yahoo](https://github.com/ranaroussi/yfinance/blob/main/README.md).

## Pendientes de definición

1. Obtener dictamen jurídico sobre los productos y entregables permitidos sin registro CNBV y
   respuesta del empleador sobre la actividad externa. Constituir una persona moral no sustituye ninguna
   de estas dos evaluaciones.
2. Obtener series por emisión para validar renovaciones del [preparador CETES](cetes_adapter.md),
   incorporar precios de salida/entrada y ampliar el catálogo con claves oficiales e ISIN.
3. Obtener y archivar tarifarios reales por contrato, cliente y producto. El importador ya concilia
   un perfil fechado y separa costos iniciales y recurrentes; falta validarlo con contratos reales.
4. Obtener cotizaciones y contratos para la ruta definida en la [matriz de fuentes](data_sources.md):
   Banxico como referencia mexicana y precios BMV/SIC aportados bajo un permiso confirmado. El
   manifiesto ya impide usar archivos con derechos pendientes, vencidos o no autorizados.
5. La importación anónima y no persistente de la cartera actual ya está disponible. Antes de
   almacenar datos, definir los campos mínimos, finalidad, acceso, conservación y eliminación de expedientes.
6. La reserva fiscal ya cubre ventas con bases actualizadas y tasas declaradas. Falta validarla con
   constancias reales y ampliar dividendos, intereses, fondos, pérdidas y personas morales con revisión fiscal.
