# Rendimiento documentado y comparación de cortes

Alcance aprobado: puntos 15–16 de `docs/siguientes_pasos_2026-11-15.md`.
Base: `6cb6293e4e927ef69547c89e58991506091b5e7f`. USD 0; muestras ficticias.

## Contratos y decisiones

- Pantalla, TXT, CSV y PDF utilizan la misma ejecución. Los ingresos y cargos
  se agrupan por instrumento y moneda, por fecha de operación: el libro incorpora
  su contrapartida pendiente antes de liquidar. Nunca sumar monedas sin FX.
- Comparar cortes requiere igual cuenta, moneda y una nueva confirmación de sus
  fuentes. Diferentes versiones del mismo corte muestran diferencias; no constituyen
  un rendimiento temporal. Si cambia el historial previo, no se atribuye rendimiento.
- Guardar un corte JSON independiente, acotado, con huella y esquema estable,
  sin originales ni autorizaciones. No reemplaza el ZIP para continuar la revisión.
  No alterar los protocolos ZIP v1–v4. La huella detecta alteraciones accidentales;
  no autentica al emisor de un archivo.
- Los precios se explican con valores inicial/final y compras/ventas brutas;
  ingresos y cargos por separado. Transferencias en especie necesitan importe
  documentado; aperturas posteriores impiden atribuir. Reportos conservan su
  principal aparte del interés; valuación ausente permanece pendiente.
- En divisas, mostrar nativo y convertir sólo con fuentes suficientes. Para una
  tenencia sin movimientos se separan precio a FX final y FX sobre valor inicial.
  Con movimientos y sin FX de cada operación, conservar el desglose base pendiente.
- Comparar TWR/XIRR guardados con su propio periodo; no restarlos como rendimiento
  entre cortes. El cambio de patrimonio no se presenta como ganancia.

## Ejecución y verificación

1. RED/GREEN: desglose por instrumento y fechas de operación, sin convertir USD
   sin fuente. Conservar comportamiento parcial y métricas independientes.
2. RED/GREEN: corte inmutable con límites, estructura, integridad, cuenta, fuentes
   y validación decimal; comparación de posiciones, efectivo y pendientes.
3. RED/GREEN: atribución entre cortes con aportaciones/retiros, compras/ventas,
   dividendos/cargos, liquidación pendiente, splits, FX, reportos y un centavo.
4. Interfaz nativa y descargas bajo demanda; cambio de insumo renueva confirmación.
   PDF de dos páginas con cifras de comparación y detalle íntegro en TXT/CSV.
5. Auditoría reproducible: pruebas Windows/Linux, Ruff, dependencias, contenedor,
   navegador 1440/768/390, axe, teclado, rendimiento, continuidad, ZIP previos y PDF.
6. Revisión independiente de la entrega completa; corregir hallazgos materiales.
   Integración y publicación autorizadas; comprobar versión y recorrido ficticio.

Casos independientes: aporte 50 a patrimonio 100→150: ganancia 0; compra 20 de
AAA y venta 24: precio 4; dividendo 3, comisión 1, impuesto .3: neto 5.7;
AAA sin movimientos 10×USD10→10×USD12, FX20→21: precio420, FX100; diferencia
de .01 se conserva. Ninguna resta de TWR/XIRR produce un retorno nuevo.

Los informes separan automatización, revisión humana y dispositivo físico. Las
valuaciones reales de julio, reporto, transferencias, GMéxico y tarifas siguen
dependiendo de evidencia; no se sustituyen por supuestos.
