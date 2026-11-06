# Operación por cuenta y preparación del entorno de prueba

La sección **Operación** reúne movimientos, implementación, fuentes y alertas,
patrimonio y revisión de originales GBM. El análisis de cartera conserva el recorrido
anterior y añade importación de posiciones desde PDF, borradores cifrados y nombres
de ejecuciones con corte y objetivo. Los originales y el piloto real permanecen fuera de Git.

## Movimientos y rendimiento

La plantilla descargable tiene estas columnas, en este orden:

```text
ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,Referencia,MomentoFlujo
```

Las fechas usan `AAAA-MM-DD`. `Importe` es el bruto positivo; comisión e impuesto se
registran por separado. Las cantidades y los importes se calculan con Decimal.
El mismo ID y contenido se importa una vez; un ID con contenido distinto se rechaza.
Las filas de un mismo día deben seguir el orden económico de las operaciones.

Tipos admitidos:

| Tipo | Efecto |
| --- | --- |
| OPEN_CASH / OPEN_POSITION | Saldos iniciales, sin atribuirlos a rendimiento del periodo |
| BUY / SELL | Títulos en operación; efectivo a liquidación y pendiente firmado mientras tanto |
| DEPOSIT / WITHDRAWAL | Flujos externos, separados de ganancia |
| DIVIDEND / COUPON / INTEREST | Cobros dentro de la cuenta; no aportaciones |
| FEE / TAX | Cargos; no retiros del inversionista |
| SPLIT | `Cantidad` es la razón nueva/anterior; conserva el efectivo |
| ASSET_IN / ASSET_OUT | Transferencias de títulos; precio unitario documenta el flujo externo |
| TRANSFER_IN / TRANSFER_OUT | Transferencias con referencia, candidatas a eliminación entre cuentas |
| FX_IN / FX_OUT | Dos patas con misma referencia y fecha, en monedas distintas |

Los eventos corporativos complejos deben desglosarse y revisarse mediante sus patas
de títulos y efectivo; el sistema no infiere fusiones, derechos o bases fiscales.
Una venta sin títulos previos se rechaza. Un saldo de efectivo negativo debe revisarse;
el libro no acredita una línea de margen ni liquidez para operar.

La valoración requiere **precios sin ajuste** y FX explícito del cierre. Combinar
dividendos en efectivo con precios ajustados duplicaría su efecto económico.
Las cotizaciones del libro y de implementación permanecen separadas de los precios
ajustados empleados por el modelo de investigación.

El rendimiento histórico utiliza cierres conciliados y flujos confirmados:

- TWR encadena subperiodos ajustados por flujos. Cada flujo necesita valuación en
  su fecha y momento `BOD` o `EOD`. Un flujo BOD requiere también el cierre del día
  calendario anterior. Si falta información, TWR queda **Pendiente**.
- XIRR usa fechas reales y años de 365 días. Los patrones que pueden tener varias
  raíces quedan pendientes de revisión; no se elige una raíz arbitraria.
- La ganancia del periodo es cierre final menos cierre inicial y aportaciones netas.
  No es una determinación de ganancia fiscal realizada ni una certificación GIPS.

## Costos y títulos

La propuesta utiliza optimización entera de lotes con comisión, mínimo por orden,
IVA sobre comisión, costo de mercado, efectivo mínimo, rotación y concentración.
La función admite además límites por clase. Rotación significa compras más ventas
divididas entre patrimonio inicial; una sustitución completa puede llegar a 200%.

El objetivo minimiza desvío de los pesos deseados más costo. Opcionalmente usa la
media y covarianza del análisis MXN abierto de la misma cuenta para obtener un
objetivo sensible al costo proporcional y a la rotación. Ese paso no aproxima una
comisión mínima como si fuera proporcional: los mínimos se resuelven en el plan de lotes.

Se vuelve a comprobar el efectivo después de redondear títulos e importes. El
importe se redondea a centavos y los cargos hacia arriba. El modelo reserva hasta
tres centavos por orden para ese redondeo conservador. Deben confirmarse las reglas
del intermediario. Si el solucionador alcanza su tiempo límite con una solución
factible, se identifica como tal; no se anuncia como óptima.

Las órdenes permanecen como propuesta descargable, sin transmisión al intermediario.
El guardado incluye insumos, tarifas, pesos objetivo, resultados y huellas del código.

## Documentos, catálogo y fuentes

El lector PDF admite el diseño GBM observado, conserva página/fila de las posiciones
y exige confirmar cuenta, MXN y correspondencias. Una categoría sin normalizar bloquea
la declaración de cartera completa. Las diferencias de un centavo se conservan como
advertencias y requieren aceptación explícita. Los movimientos extraídos se muestran
como candidatos revisables; las filas desconocidas no se contabilizan automáticamente.

El XML se valida como evidencia de cargos. **Un CFDI no crea un segundo cargo**:
debe vincularse y conciliarse contra un movimiento antes de contabilizar importes.
No se valida el timbrado ante SAT ni se infiere tratamiento fiscal.

El catálogo CSV usa:

```text
Instrumento,ISIN,Mercado,EmisorID,Emisor,Tipo,Sector,Pais,Moneda,Lote,Fecha,Fuente
```

Se comprueba dígito verificador del ISIN, unicidad de instrumento e ISIN/mercado,
lote positivo, fecha y procedencia. `EmisorID` debe venir de una taxonomía estable y
revisada; el validador no acredita por sí mismo la autenticidad de esa asignación.
Aplicar el catálogo modifica la preparación de la cuenta; hay que recalcular para
actualizar resultados. El archivo original acompaña al paquete de la ejecución.

El formato previo de componentes sigue admitido. Puede añadirse `EmisorID` después
de `Fuente`; así se agregan alias del mismo emisor. Se muestran cobertura total,
cobertura con ID estable y cobertura con antigüedad máxima de 90 días. El peso sin
componentes permanece **Sin cobertura**.

Las fuentes periódicas son archivos CSV en carpetas aprobadas por administración:
cotizaciones, componentes o catálogo. No hay descarga universal de datos licenciados.
Cada fuente declara permiso vigente y, para precios, ajuste `raw` o `adjusted`.
Un fallo conserva la última entrada válida, mostrando estado, antigüedad y hora del intento.
La carga recibida debe revisarse antes de incorporarse a un análisis.

## Alertas y persistencia

Se programa cada fuente por cuenta. Se generan alertas dentro de la app cuando
cambia su disponibilidad o condición de antigüedad, y opcionalmente al cambiar el
contenido. Los fallos idénticos no producen una nueva alerta en cada revisión.

Puede fijarse un monitor de desvío con las cantidades conciliadas del libro y la
referencia del análisis de la misma cuenta. Exige MXN, instrumentos coincidentes,
liquidación revisada y cotizaciones sin ajuste de un cierre común. Compara los pesos
invertidos, excluyendo efectivo. Las cantidades deben actualizarse después de operar.
Se avisa al cruzar la tolerancia o al faltar información compatible, sin notificaciones externas.

Borradores, suscripciones, datos recibidos y alertas se cifran con la clave del
expediente, ligados a cuenta y propietario. Cada lectura comprueba acceso vigente.
Las escrituras usan versión esperada para impedir sobrescribir un borrador más
reciente. No modifican la revisión financiera hasta adjuntar evidencia expresamente.

## Patrimonio y transferencias

Las posiciones consolidadas requieren mismo corte, moneda de origen, cuenta y FX
con fuente para ese corte. No se mezclan pesos con dólares sin conversión explícita.
El ID de emisor permite agrupar exposiciones a través de instrumentos y cuentas;
la cobertura de identidad se mide sobre valores absolutos, incluyendo pendientes.

El rendimiento consolidado requiere un calendario de cierres común para todas las
cuentas y FX en cada cierre. Los flujos declaran además el FX a su propio momento.
Sólo se eliminan pares de transferencias con referencia, fecha, moneda e importe
iguales y cuentas distintas. Una pata sin pareja bloquea ese cálculo hasta revisarla.
Una transferencia no se resta del patrimonio; se elimina de los flujos externos.
Las conversiones entre monedas requieren sus patas FX, no se cancelan como si fueran
transferencias en una misma moneda.

## Entorno de prueba recomendado

Se entrega `Dockerfile`, `.dockerignore`, `compose.yaml` y `render.yaml`. El blueprint
usa Render `1c-2g`, una instancia y un disco de 5 GB en `/var/data`. App y trabajador
corren en el mismo contenedor porque el disco no puede compartirse entre servicios.
El arranque requiere OIDC válido, al menos una identidad ADMIN y registros bajo
el disco persistente. El proceso de aplicación corre con usuario sin privilegios.
Un fallo de configuración detiene el arranque, sin imprimir secretos.

Referencia de precio consultada: cómputo USD 25/mes más disco USD 0.25/GB/mes:
5 GB dan una base estimada de **USD 26.25/mes**, antes de impuestos y consumos extra.
No se ha contratado este servicio. Verificar el total en la cuenta antes de activarlo.

Pasos de activación:

1. Revisar los cambios y las pruebas de contenedor en CI.
2. Crear el servicio desde el blueprint sólo después de autorizar el costo.
3. Registrar en OIDC `https://<dominio-del-servicio>/oauth2callback` y las identidades
   verificadas. Configurar el TOML en `SIG_SECRETS_TOML` desde el gestor de secretos.
4. Usar `/var/data/workspace/cases.db` y `/var/data/technical.db`, con clave Fernet
   custodiada fuera del disco. Comprobar permiso de escritura para UID 10001.
5. Inicializar Expedientes mediante la identidad ADMIN y probar acceso, reinicio y
   recuperación con datos ficticios antes de incorporar documentos autorizados.
6. Activar `[operations].enabled` sólo para fuentes y cuentas aprobadas.

El disco limita la operación a una instancia y requiere una breve interrupción al
desplegar. No es todavía una arquitectura para múltiples réplicas.

## Respaldos y recuperación

Con `operations.backup_enabled=true` se crea un paquete cifrado por día UTC junto
a la base de expedientes, en `backups/`. Incluye casos, borradores, trabajos, alertas
y la base separada de seguimiento, si existe. Cada SQLite se respalda con su API
consistente y se verifica. No hay una transacción conjunta entre las dos bases;
para un corte operativo coordinado, detener escrituras durante el respaldo.

También puede ejecutarse como operador local:

```powershell
python -m scripts.backup_workspace --config <TOML-privado> --admin-subject <ADMIN-verificado> --destination <archivo.sigbackup> --bundle
python -m scripts.backup_workspace --config <TOML-privado> --admin-subject <ADMIN-verificado> --destination <archivo.sigbackup> --bundle --check-only
python -m scripts.backup_workspace --config <TOML-privado> --admin-subject <ADMIN-verificado> --destination <archivo.sigbackup> --bundle --restore-to <directorio-nuevo>
```

La restauración verifica cifrado, inventario, hashes, integridad SQLite, auditoría y
vínculo de registros operativos antes de escribir. No sobrescribe registros existentes.
La clave debe recuperarse por un canal separado. Descargar una copia cifrada fuera
del proveedor es una tarea del operador; una copia en el mismo disco no cubre pérdida
de ese disco. No restaurar una instantánea del proveedor sobre una base en ejecución.

Fuentes técnicas: [Render, planes](https://render.com/docs/compute-plans),
[precios](https://render.com/pricing), [discos](https://render.com/docs/disks),
[blueprint](https://render.com/docs/blueprint-spec),
[SciPy MILP](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html),
[XIRR](https://support.microsoft.com/en-us/office/xirr-function-de1242ec-6477-445b-b11b-a303ad9adc9d).
