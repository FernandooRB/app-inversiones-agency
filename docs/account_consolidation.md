# Consolidación de valuaciones por cuenta

La pestaña Consolidado del expediente permite preparar un consolidado interno de posiciones
cuando ya se registraron al menos dos cuentas. Usa `account_consolidation.py` y los importadores
existentes. No es una optimización conjunta ni un informe de rendimiento.

El analista selecciona las cuentas y declara, para cada una, instrumentos y tres archivos:
posiciones al corte, cobertura de cuenta e identidad de series locales MXN. Debe cotejar su
pertenencia y corte antes de preparar y guardar el resultado. El paquete con JSON y PDF queda
cifrado como archivo del expediente y requiere nuevas revisiones de la versión.

Los cortes deben coincidir. No se aceptan alias repetidos, el mismo archivo de posiciones sumado
dos veces, identidades incompatibles para una etiqueta, símbolos incompatibles de una misma serie
o proxys extranjeros. La coincidencia de cifras no acredita pertenencia; dos cuentas genuinamente
idénticas requieren tratamiento y comprobación adicionales, no desactivar la detección de duplicados.

Las posiciones se suman por ISIN y mercado; el efectivo externo, liquidaciones y otras partidas se
muestran por separado. Los importes se concilian al centavo con Decimal. Los pesos se refieren sólo
a las posiciones analizadas y no incorporan el efectivo externo.

No se agregan los patrimonios para deducir tramos de corretaje; cada cuenta conserva su tarifa,
costos, situación fiscal y restricciones. Tampoco se combinan rendimientos de periodos distintos.
El consolidado produce un paquete con JSON auditable y PDF interno; las monedas extranjeras,
la atribución de rentabilidad entre cuentas y la optimización conjunta son etapas
posteriores que requieren datos y validación específicos.
