# Catálogo piloto de instrumentos México y SIC

El catálogo versionado en `data/instrument_catalog.csv` separa el instrumento negociable de la
serie usada para analizarlo. Esta distinción evita introducir al optimizador series que no representan
un retorno total comparable.

## Estados de integración

| Estado | Uso actual |
| --- | --- |
| `DIRECTO_ACTUAL` | El motor puede descargar una serie ajustada en la misma moneda declarada. |
| `DIRECTO_CON_PROXY` | El motor usa la serie del mercado de origen y la convierte a la moneda base. |
| `PREPARACION_ARCHIVO` | El usuario aporta los insumos de valoración requeridos por el instrumento; la app prepara y valida el índice antes del análisis. |
| `REQUIERE_ADAPTADOR` | Falta valoración específica, flujos, NAV o una fuente oficial integrada. |
| `REFERENCIA_NO_INVERTIBLE` | La serie sirve para conversión o contraste, no como posición. |

Para un valor del SIC, la serie extranjera convertida a MXN aproxima su exposición económica. No
reproduce la cotización local, el spread, la profundidad, la ejecución ni los costos del intermediario.
La BMV describe al SIC como la plataforma para acciones y ETF extranjeros y señala que opera en pesos.

Los CETES se modelan como instrumentos a descuento con valor nominal, plazo y precio. Las series de
tasas no se transformarán directamente en retornos diarios. El adaptador deberá seleccionar una serie de
precios de Banxico y documentar cómo mantiene o rola vencimientos comparables. Los Bonos M requieren
emisión, cupón semestral, vencimiento y tratamiento de precio limpio, interés devengado y flujos. El
[adaptador de Bonos M](bonos_m_adapter.md) ya prepara una emisión desde un CSV; aún requiere contraste
externo de sus precios, devengado y calendario antes de un uso comercial.

El [adaptador de liquidez MXN](liquidity_adapter.md) prepara un vehículo identificado desde su tasa
anual histórica y una convención explícita. La etiqueta `NETA` es una declaración de la fuente; la app
no calcula impuestos ni verifica disponibilidad, comisiones, protección de depósitos o riesgo de crédito.

El [adaptador de fondos MXN](fund_adapter.md) exige un fondo y una serie constantes, y combina el valor
de la acción con distribuciones en efectivo. No confirma que el valor aportado sea ejecutable, que incluya
todos los costos ni que la serie esté disponible para un cliente determinado.

## Reglas operativas

1. Confirmar símbolo, serie, ISIN, mercado y moneda con una fuente autorizada antes de analizar.
   El [manifiesto de identidad](instrument_identity.md) detecta inconsistencias formales para los
   tickers de precios, pero no sustituye esa confirmación externa.
2. Registrar la fuente y fecha de corte utilizadas en cada expediente de investigación.
3. No sustituir un instrumento sin datos con un índice o ETF sin marcarlo explícitamente como proxy.
4. Validar derechos de uso comercial y distribución de datos antes de generar entregables para terceros.
5. Mantener fuera del optimizador cualquier fila con `REQUIERE_ADAPTADOR`.

Fuentes iniciales:

- [BMV: Mercado Global (SIC)](https://bmv.com.mx/es/mercados/mercado-global)
- [Banxico: precios y tasas de CETES](https://www.banxico.org.mx/SieInternet/consultarDirectorioInternetAction.do?accion=consultarCuadro&idCuadro=CF300)
- [Banxico: características de CETES y Bonos M](https://www.anterior.banxico.org.mx/dyn/divulgacion/sistema-financiero/sistema-financiero.html)
- [CNBV: Portafolio de Información](https://portafolioinfo.cnbv.gob.mx/)
