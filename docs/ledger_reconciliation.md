# Controles de cierre del libro

En **Operación → Movimientos → Conciliar contra el estado de cuenta** se puede
contrastar el libro con saldos del mismo cierre y cuenta. La comparación no crea
movimientos, no reemplaza saldos iniciales y no acepta diferencias de centavos.

La plantilla CSV utiliza estas columnas en este orden:

```text
Fecha,Tipo,InstrumentoReferencia,Moneda,Saldo,Fuente
```

Las fechas usan `AAAA-MM-DD`, la moneda es MXN o USD y `Fuente` identifica el
documento y su ubicación. Los saldos se conservan como Decimal, sin conversión
de moneda ni redondeos para hacerlos coincidir.

| Tipo | `InstrumentoReferencia` | `Saldo` |
| --- | --- | --- |
| `CASH` | Vacío | Efectivo liquidado en esa moneda |
| `PENDING` | Vacío | Efectivo pendiente firmado: cobro positivo, pago negativo |
| `POSITION` | Instrumento del libro | Cantidad de títulos, incluida una cantidad cero explícita |
| `REPO` | Referencia del reporto | Capital vigente documentado, sin inferir su devengo |

Los controles de `REPO` no sustituyen la [valuación del reporto](repo_ledger.md)
necesaria para calcular patrimonio. Una cantidad de títulos se compara en títulos,
no en pesos. Los saldos de dos monedas no se compensan entre sí.

## Interpretar el resultado

- **Coincide:** saldo del libro y control son exactamente iguales.
- **Diferencia:** libro menos control es distinto de cero, incluso por un centavo
  o una fracción de título.
- **Sin control:** hay un saldo en el libro que no tiene control aportado. Un
  control ausente no significa cero, aunque el saldo calculado sea cero.

Si el estado declara un instrumento que el libro no contiene, el saldo calculado
para ese instrumento es cero y se muestra la diferencia; la fila no se ignora.
Las filas duplicadas y las fechas diferentes del cierre elegido se rechazan.
El resultado global sólo indica coincidencia aritmética cuando todas las filas
coinciden y no falta ningún control de los saldos representados en el libro.
Esto no demuestra que el estado o el propio libro estén completos o autenticados.

## Conservar la diferencia entre cortes

Supón un saldo inicial ficticio de 100 y un estado que imprime 100.01. La
diferencia del libro es −0.01. Si después se registra un dividendo de 10 y el
estado siguiente imprime 110.01, el libro sigue teniendo 110 y la misma diferencia
de −0.01. Abrir otra vez el libro con 100.01 escondería el descuadre.

El saldo inicial del siguiente estado sirve como control de continuidad. Una
corrección necesita evidencia y su tratamiento revisado; esta herramienta no
genera asientos para cuadrar. Los saldos corridos del documento y el efectivo
liquidado requieren respetar las fechas de operación y liquidación.

## Evidencia y alcance

La descarga JSON conserva fecha, valores y unidades originales, diferencias,
fuentes y huellas del libro, del CSV de controles y de los módulos utilizados.
Los valores completos están en esa descarga; la tabla usa una presentación
compacta de las cifras. En un expediente persistente configurado se puede
adjuntar la conciliación como evidencia versionada. En el alojamiento gratuito
se conserva mediante descarga y no se crea almacenamiento permanente.

La comparación no valida contrapartes de traspasos, movimientos omitidos, derechos
corporativos ni autenticidad de documentos. Tampoco acredita rendimiento, flujos
externos o una conciliación integral de cuenta. El [cálculo de rendimiento](operations_9_16.md)
conserva sus requisitos de valuaciones y flujos revisados.
