# Política y matriz de fuentes de datos

Revisión documental: 17 de septiembre de 2026. Esta matriz sirve para seleccionar insumos; no
concede derechos ni sustituye el contrato del proveedor. Cada producto, mercado y uso debe quedar
confirmado por escrito antes de cargar sus precios en la aplicación.

| Fuente | Cobertura útil | Evidencia oficial revisada | Uso actual en el proyecto | Decisión |
| --- | --- | --- | --- | --- |
| Banco de México SIE | FIX, tasas, CETES, precios y referencias de deuda | La [API SIE](https://www.banxico.org.mx/SieAPIRest/swagger/index.html) permite consultar metadatos y rangos históricos mediante token. | Fuente primaria candidata para FX y tasas; los adaptadores aún reciben archivos auditables. | **Prioritaria**, pero confirmar atribución, límites y uso en entregables antes de automatizar. |
| Grupo BMV | Cierres BMV, cierres SIC, fondos, eventos y datos de referencia | El [catálogo de bases](https://cognos.bmv.com.mx/es/productos-de-informacion/bases-de-datos) ofrece productos separados y remite a listas 2026 y cotización. Las tarifas distinguen uso interno, aplicaciones y redistribución. | No existe conexión contratada. | **Cotizar**. El feed directo y la redistribución no caben en el presupuesto inicial sin una oferta específica. |
| BIVA | Último hecho, nivel 1, profundidad y noticias | El [contrato y anexo](https://www.biva.mx/informacion_de_mercado/market_data/productos_biva/) separa uso interno, externo, aplicaciones automatizadas e información derivada. El anexo publicado cobra aplicaciones automatizadas desde USD 1,000 mensuales. | No existe conexión contratada. | **Descartada para el piloto** por costo; reevaluar al crecer el servicio. |
| Intermediario del cliente | Estados de cuenta, valuaciones y posibles exportaciones de precios | Depende del contrato concreto con GBM, Actinver, Bursanet, Finamex o Kuspit. Acceso del cliente no implica permiso de reutilización comercial. | Se aceptan archivos anónimos y no persistentes. | **Viable caso por caso** si el contrato permite investigación interna o entregables derivados. |
| Proveedor comercial de mercado de origen | Acciones y ETF extranjeros que pueden estar listados en SIC | Cobertura, ajustes, FX y derechos dependen del producto contratado y de las bolsas de origen. | Sin proveedor seleccionado. | **Solicitar prueba y contrato**; exigir cobertura histórica por símbolo, eventos corporativos y permiso para entregables. |
| Yahoo mediante `yfinance` | Exploración de acciones, ETF y FX | El [proyecto yfinance](https://github.com/ranaroussi/yfinance) declara uso de investigación/educación y remite a términos de Yahoo; también señala que la API está destinada a uso personal. | Descarga exploratoria predeterminada. | **No apta como fuente contractual comercial**. No usar para entregables de clientes. |

## Arquitectura recomendada dentro del presupuesto

1. Mantener Yahoo únicamente para desarrollo y pruebas exploratorias sin datos de clientes.
2. Usar Banxico para referencias mexicanas una vez documentados token, series, hora, revisiones y
   términos aplicables.
3. Para BMV/SIC, recibir precios desde una exportación o proveedor contratado y acompañarlos con el
   manifiesto de derechos. La aplicación rechaza licencias pendientes, vencidas, no autorizadas o
   archivos que no se declaren ajustados.
4. Separar tres alcances: `INVESTIGACION_INTERNA`, `ENTREGABLES_DERIVADOS` y
   `REDISTRIBUCION_DATOS`. Un permiso más amplio debe constar expresamente; no se infiere.
5. No mostrar ni adjuntar precios individuales al cliente si el permiso cubre sólo resultados
   derivados. El PDF metodológico contiene métricas y fuente, no una licencia de redistribución.

## Expediente mínimo de una fuente

Conservar fuera del repositorio público el contrato o permiso, la cotización, el contacto comercial,
la fecha de revisión, vigencia, mercados, producto, usuarios autorizados, uso automatizado, derecho a
crear entregables y reglas de redistribución. En la sesión de la app sólo se carga el manifiesto CSV;
su huella SHA-256 vincula el análisis con la declaración revisada sin guardar el contrato.

El manifiesto no prueba que la declaración sea correcta. La persona revisora debe contrastarla con el
contrato vigente y volver a emitirla cuando cambie el producto, alcance, mercado o vigencia.
