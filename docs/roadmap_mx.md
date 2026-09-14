# Plan de desarrollo: análisis de carteras en MXN

## Alcance acordado

- Uso interno por el asesor y su equipo; entrega de reportes PDF a clientes después de revisión humana.
- Clientes personas físicas y morales en México; instrumentos de mercados mexicanos y del SIC.
- Presupuesto recurrente inicial para datos y alojamiento: menos de MXN 1,000 al mes.
- Primera entrega: comparativo histórico en MXN para un caso ficticio, sin expedientes reales.
- Intermediarios prioritarios para investigar costos e importación: GBM, Actinver, Bursanet,
  Finamex y Kuspit. Finsus requiere evaluar por separado sus productos y disponibilidad de datos.

## Etapas y criterios de aceptación

| Etapa | Entrega | Criterio de aceptación |
| --- | --- | --- |
| 1. Comparativo | Máximo Sharpe, mínima volatilidad, pesos iguales y cartera actual opcional en un PDF | Mismos activos, fechas, moneda y supuestos; pesos válidos; PDF legible; pruebas automatizadas |
| 2. Datos mexicanos | Catálogo de instrumentos, serie FX independiente y referencias de tasas | Fuente, licencia, moneda, horario, ajustes y fechas documentados; sin retornos diarios falsos por huecos |
| 3. Instrumentos | Acciones/ETF mexicanos y SIC; CETES, fondos y efectivo con modelos propios | Valoración y flujos apropiados por tipo; no tratar rendimiento a vencimiento como retorno total diario |
| 4. Optimización | Objetivos y límites por perfil, cartera actual, referencias y sensibilidad | Restricciones factibles; comparación con alternativas simples; diagnósticos de estabilidad |
| 5. Simulación | Trayectorias Monte Carlo con aportaciones, retiros, inflación, costos y rebalanceo | Semilla y supuestos guardados; resultados hipotéticos; pruebas de sensibilidad y estrés |
| 6. Validación | Ventanas fuera de muestra, referencias y costos | Fechas de estimación/evaluación separadas; límites y fallos comunicados |
| 7. Expedientes | Historial de propuestas y aprobación del asesor | Roles, trazabilidad, aviso de privacidad, conservación y respaldo definidos antes de guardar datos reales |

## Decisiones metodológicas iniciales

- Optimización inicial de posiciones largas sin apalancamiento; límites por activo configurables.
- Índices como referencias; la inversión en un índice se representa con un vehículo identificable.
- El comparativo de la etapa 1 es histórico. No incluye comisiones, impuestos ni una recomendación
  personalizada. La cartera actual es una referencia ingresada por el usuario y no tiene que cumplir
  el límite de concentración de las carteras optimizadas.
- No se mezcla automáticamente la cotización local en MXN de un valor SIC con una conversión USD/MXN:
  el catálogo debe registrar mercado, moneda de cotización y exposición económica.
- La certificación AMIB Figura 3 declarada por el usuario no se tratará como verificación de
  inscripción en el Registro de Asesores en Inversiones de la CNBV. Antes de generar recomendaciones
  personalizadas, confirmar el encuadre regulatorio y la inscripción aplicable.
- Los impuestos se presentan por separado después de definir instrumento, intermediario y régimen
  fiscal del cliente; no se aplica una tasa universal.

## Fuentes a evaluar

- [CNBV: Registro de Asesores en Inversiones](https://www.gob.mx/cnbv/acciones-y-programas/registro-de-asesores-en-inversiones-rai).
- [Banco de México: convenciones del FIX](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF85).
- [Banco de México: series de CETES](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF107).
- [SAT: enajenación de acciones](https://wwwmat.sat.gob.mx/articulo/59621/articulo-129).
- [yfinance: condiciones de uso de datos Yahoo](https://github.com/ranaroussi/yfinance/blob/main/README.md).

## Pendientes de definición

1. Confirmar si existe inscripción vigente ante la CNBV, además de la certificación AMIB, y el
   proceso de transición previsto a persona moral.
2. Elegir un vehículo real del SIC, una acción mexicana y un producto de deuda para el piloto.
3. Obtener tarifarios reales de los intermediarios usados; elegir uno para la primera importación.
4. Seleccionar un proveedor de datos apropiado para el uso comercial dentro del presupuesto o
   delimitar un flujo con datos aportados por el intermediario y fuentes oficiales.
5. Definir los campos mínimos y política de conservación de expedientes antes de almacenar datos.
