# Flujos fiscales documentados en MXN

El equipo puede importar un CSV anónimo de **flujos ya cobrados**, con un solo ejercicio fiscal y
fecha de pago anterior o igual al corte de la cartera actual, si existe, o al día de ejecución. Los
instrumentos deben pertenecer al universo analizado, pero el archivo no exige flujos de todos ellos.
No se vincula a una identidad, se guarda ni se extrapola automáticamente a alternativas propuestas.

Columnas exactas, en orden:

`FechaPago,Instrumento,TipoFlujo,ImporteBrutoMXN,ISRRetenidoMXN,ImpuestoExtranjeroRetenidoMXN,TratamientoFiscal,BaseRetencionMXN,DiasPeriodo,TasaControlPct,TasaReservaAdicionalPct,Fuente`

`TipoFlujo`: `INTERES`, `DIVIDENDO_MEX`, `DIVIDENDO_EXTRANJERO_SIC`,
`DISTRIBUCION_FONDO_DEUDA`, `DISTRIBUCION_FONDO_RV`. Cada fila representa un pago documentado, no
una posición ni una estimación de cobros futuros. Para fondos, la clasificación requiere la constancia
de la serie y el desglose fiscal de la distribución: no se infiere por la etiqueta del fondo.

| `TratamientoFiscal` | Campos requeridos | Alcance |
| --- | --- | --- |
| `PF_DIVIDENDO_MEX_ART140` | Sólo `DIVIDENDO_MEX`; base igual al bruto, tasa de control 10%; días y reserva adicional vacíos | Control del ISR adicional retenido, sin calcular acumulación, impuesto corporativo acreditable ni anual |
| `PF_INTERES_LIF2026` | Sólo `INTERES` de 2026; base de capital positiva, 1-366 días enteros, tasa de control 0.90%; reserva adicional vacía | Control ilustrativo: base × 0.90% × días / 365; la retención real puede seguir reglas particulares y consta por separado |
| `RETENCION_DOCUMENTADA` | Bases, días y tasas vacíos | Retenciones aportadas según constancia; sin tasa calculada |
| `ESCENARIO_TASA_ADICIONAL` | Sólo tasa adicional de 0-100%; bases, días y tasa de control vacíos | Reserva adicional explícita sobre el bruto, independiente de retenciones; no representa saldo a pagar |
| `NO_ESTIMADO` | Bases, días y tasas vacíos | Muestra el bruto pendiente de clasificación sin inventar una reserva |

`ISRRetenidoMXN` e `ImpuestoExtranjeroRetenidoMXN` son importes **documentados**, no inferidos. Deben
ser finitos, no negativos y su suma no puede exceder el bruto. El CSV original queda identificado por
SHA-256 en los resultados. El control calculado, la diferencia respecto al ISR documentado, las
retenciones nacionales y extranjeras, la reserva adicional y los flujos sin estimación se muestran
separadamente. No se suman a la reserva por ventas, no se compensan entre flujos, ni se determina la
declaración anual, acreditamientos extranjeros, impuestos de fondos, régimen de persona moral o
tratamiento específico de títulos SIC. El resultado requiere revisión fiscal humana.

## Referencias revisadas el 21 de septiembre de 2026

- [LISR art. 140](https://wwwmat.sat.gob.mx/articulo/32450/articulo-140): acumulación de dividendos
  para personas físicas, acreditamiento sujeto a requisitos y retención adicional definitiva de 10%
  sobre dividendos distribuidos por personas morales residentes en México.
- [LISR art. 135](https://wwwmat.sat.gob.mx/articulo/89366/articulo-135): retención por intereses sobre
  capital como pago provisional, con supuestos específicos que requieren revisión.
- [LIF 2026 art. 24](https://dof.gob.mx/nota_detalle_popup.php?codigo=5772357): tasa anual general
  de 0.90% aplicable en 2026 a las referencias indicadas de los artículos 54 y 135 de la LISR.
- [Reglamento LISR art. 231](https://wwwmat.sat.gob.mx/articulo/04209/articulo-231): información
  sobre dividendos subyacentes en fondos de renta variable y sus constancias.
