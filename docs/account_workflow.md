# Análisis por cuenta

El recorrido está en **Análisis → Por cuenta**. También se abre desde **Expedientes → Cuenta y perfil → Analizar esta cuenta**. Permite preparar una cartera MXN, comparar alternativas, estudiar su exposición y una meta, guardar los insumos y retomar la investigación.

## Preparar una cuenta

Selecciona un expediente y una cuenta MXN. Si el registro no está configurado, puedes trabajar temporalmente y descargar un paquete para retomar. El guardado en el registro conserva el control de acceso, cifrado, versiones y revisiones existentes.

La demostración usa instrumentos `SIM-A`, `SIM-B` y `SIM-F`, series generadas y componentes ficticios. No descarga cotizaciones ni usa cuentas reales.

### Posiciones GBM

Se admite el diseño XLSX observado de **Mercado de Capitales Nacional** y **Efectivo**, con una hoja y los encabezados reconocidos por el inspector existente. Otros diseños, PDF, operaciones y eventos corporativos no se importan automáticamente en este recorrido.

La pantalla muestra etiqueta, fila original, cantidad, precio, valor y diferencia aritmética. Debes:

1. Asignar un símbolo local único a cada fila.
2. Declarar y cotejar el corte del documento.
3. Confirmar que las valuaciones están en MXN.
4. Cotejar el total de cuenta contra posiciones más efectivo.
5. Resolver diferencias de cantidad × precio contra valor antes de confirmar.

Se rechazan fórmulas, archivos con partes externas o macros, etiquetas duplicadas, posiciones sin correspondencia y diferencias de valuación. La correspondencia confirmada, las filas y la huella del documento quedan en el paquete de la ejecución. Que la aritmética coincida no acredita autenticidad, titularidad o completitud de operaciones.

También se admite el CSV normalizado existente: `FechaCorte,Instrumento,ValorMXN`. El efectivo externo se declara por separado y no aumenta los pesos del capital analizado.

### Precios y procedencia

Carga cierres locales ajustados MXN con `Fecha` y una columna por instrumento. La historia se recorta al periodo elegido, sin incorporar cotizaciones posteriores al corte. Puedes cargar el manifiesto de derechos existente o declararlo en el formulario de procedencia, con fuente, producto, mercados, fechas, horario de cierre, referencia y uso permitido comprobado.

La identidad/ISIN es opcional para investigación interna y su ausencia queda como pendiente. Los proxies de origen se mantienen en Análisis avanzado. Este recorrido no incorpora automáticamente una segunda fuente independiente; lo declara entre los pendientes.

## Comparar alternativas

Se calculan sobre el mismo universo, muestra y estimador:

- Conservar la cartera.
- Cambio parcial hacia mínima volatilidad, con una fracción declarada.
- Mínima volatilidad.
- Máximo Sharpe.
- Pesos iguales.

Se muestran media histórica, volatilidad, CVaR diario en pesos, rotación, costos del cambio, cargos recurrentes, efectivo restante y cumplimiento del tope por activo. El tope restringe las propuestas optimizadas; la cartera actual y el acercamiento parcial pueden conservar una concentración anterior, señalada en la tabla.

Los supuestos generales de costos usan el estimador existente de compras/ventas, comisión, IVA, mínimos y costo de mercado. Requieren confirmación, fuente y fecha. Los costos faltantes aparecen pendientes. Conservar no genera transacciones y puede tener cargos de mantenimiento.

Los costos iniciales del cambio se financian con el efectivo externo declarado. Una alternativa sin efectivo suficiente se marca y no recibe simulación de meta. Los importes son teóricos: no son órdenes ni incorporan lotes, redondeo de títulos, impuestos o disponibilidad real de ejecución. La comparación no convierte una media histórica en retorno neto esperado.

La referencia para seguimiento y su tolerancia se eligen antes de ejecutar. Son parámetros de revisión; no aprueban una recomendación u operación.

## Estimador y cálculo

Análisis avanzado, el piloto local y el recorrido por cuenta comparten `model_estimation.py`. Se ofrece covarianza muestral, contracción diagonal de 50% y contracción diagonal calibrada. El valor inicial compartido es calibrada; necesita 100 retornos y nunca cambia silenciosamente a otro método cuando faltan datos.

La calibración es el protocolo cronológico existente de candidatos diagonales. No equivale a validación externa del resultado ni garantiza estabilidad futura. El método e intensidad se conservan en la ejecución y el PDF.

Los resultados se conservan en la sesión del usuario con claves que incluyen entradas y parámetros. Una modificación invalida la ejecución correspondiente. Los módulos opcionales de Análisis avanzado también conservan sus cálculos. Los PDF se generan al solicitarlos y la descarga no vuelve a ejecutar el modelo.

Al calcular por cuenta se pliega la preparación para dar prioridad a los resultados. Si editas un supuesto, aparece el aviso de cambios sin calcular; las descargas conservan la configuración de la ejecución anterior hasta volver a analizar.

## Exposición de fondos

Puedes declarar tipo, emisor, sector, país, moneda económica y fuente de cada posición, y aportar componentes de ETF/fondos:

`Fondo,Componente,Peso,Emisor,Sector,Pais,Moneda,Fecha,Fuente`

`Peso` usa fracciones de 0 a 1. Cada fondo tiene una fecha no posterior al corte, componentes únicos y suma no mayor a 1. Se admiten archivos parciales: el resto se conserva como **Sin cobertura**. Los componentes no se consultan automáticamente ni se suponen actuales por haberlos aportado.

La exposición agrega pesos directos e indirectos por emisor, sector, país y moneda, y muestra emisores presentes mediante varios instrumentos. La agregación requiere identificadores/nombres de emisor consistentes en las fuentes declaradas; no los resuelve contra un registro externo. Cotizar en MXN no determina por sí solo la exposición económica.

La demostración tiene 97% de cobertura y 3% desconocido para comprobar que una cobertura parcial no se interpreta como diversificación adicional.

## Metas y Monte Carlo

Define monto, unidades nominales o pesos de hoy, horizonte de 1–120 meses, inflación, aportación **o** retiro mensual, método, trayectorias y semilla. El horizonte y objetivo del perfil se pueden usar como punto de partida; capacidad y tolerancia de pérdida permanecen separadas.

La meta incluye posiciones y efectivo externo después del costo inicial confirmado. El efectivo se representa como una serie sin rendimiento y exenta del cargo porcentual. El costo proporcional se aplica al capital invertido; el cargo fijo anual se reparte en doce cargos mensuales. Los cargos fijos no cubiertos se registran por trayectoria. Los flujos se distribuyen con los pesos iniciales, al cierre mensual, sin rebalanceo.

No se simulan impuestos ni cargos por las operaciones futuras que podrían requerir esos flujos. Si el tarifario está sin confirmar, la simulación queda identificada como bruta. La frecuencia de alcanzar la meta, el déficit y los retiros no cubiertos son resultados del modelo y sus supuestos.

El gráfico y la meta usan las mismas unidades: nominales o pesos de hoy. Las alternativas usan la misma muestra, método, flujos y semilla. La meta no modifica automáticamente la asignación.

## Guardar, retomar y comparar cortes

La ejecución contiene identificador, configuración con campos nombrados, fecha del cálculo, versión del esquema y huella del código, perfil usado, clasificación, revisión de importación, resumen y archivos con huellas SHA-256. El paquete evita serializar objetos ejecutables y comprueba nombres, tamaños y huellas al abrirlo.

En el expediente se adjunta cifrado y vinculado a la cuenta. Si generas el PDF antes de guardar, también queda dentro del paquete, con su huella, y puede descargarse al retomar. Adjuntarlo crea una revisión nueva e invalida las revisiones anteriores conforme a la operación existente. Recalcular crea una ejecución nueva; no sobrescribe la anterior. Los permisos se vuelven a comprobar al acceder al expediente o archivo.

El paquete descargado contiene los insumos originales y requiere la misma custodia. Sus huellas comprueban correspondencia entre archivos; no son una firma del proveedor ni acreditan que un documento externo sea auténtico. La versión guardada permite ver el resumen y recuperar entradas; si cambió el motor se informa antes del nuevo cálculo. Los derechos deben seguir siendo válidos para ejecutar otra investigación.

La comparación de cortes exige misma cuenta/expediente y orden temporal. Muestra cambios de valuación, pesos y desvío respecto de la referencia del corte anterior, con su tolerancia. Los activos nuevos sin referencia quedan sin objetivo conocido. Los cambios de saldo no se presentan como rendimiento realizado: aportaciones, retiros y operaciones necesitan un libro conciliado antes de calcularlo.

## Alcance operativo

Esta entrega implementa las ocho prioridades del recorrido descrito. Mantiene el uso interno y los controles del piloto existentes. La importación se limita al diseño GBM descrito; datos de mercado, componentes y tarifas requieren fuentes declaradas. La contabilidad integral de movimientos, rendimiento realizado multicuenta y ejecución de cantidades negociables siguen siendo ampliaciones distintas.
