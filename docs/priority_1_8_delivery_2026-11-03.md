# Entrega de las prioridades 1 a 8

Fecha: 3 de noviembre de 2026. Cambios locales en el proyecto.

## Correcciones comprobadas

- **Benchmark:** moneda sin selección inicial; se exige confirmarla cuando hay ticker, antes de consultar al proveedor. No se deduce una moneda por el sufijo del símbolo.
- **Estimador compartido:** análisis avanzado, piloto y recorrido por cuenta usan el mismo módulo y método explícito. La prueba de paridad compara intensidades y pesos de ambas rutas. El método calibrado exige 100 retornos y no cambia silenciosamente a muestral.
- **Repetición del cálculo:** resultados acotados por sesión, identificados por entradas y parámetros; módulos opcionales conservan sus cálculos. PDF a demanda, por separado, y descargas sin repetir el modelo. Cambiar de identidad limpia los datos y resultados privados de la sesión.

## Funciones incorporadas

| Prioridad | Entrega funcional | Alcance |
| --- | --- | --- |
| 1 | Importación GBM XLSX revisada por fila o cartera CSV | Diseño observado de capitales/efectivo, hasta 25 instrumentos, correspondencias confirmadas, control cantidad × precio y total con efectivo |
| 2 | Ejecución por cuenta con insumos, configuración, resultados y revisión de importación | Archivo cifrado en Expedientes o paquete descargable; PDF incluido si se genera antes de guardar; reapertura y huellas verificadas |
| 3 | Conservar, cambio parcial, mínima volatilidad, máximo Sharpe y pesos iguales | Misma muestra/estimador, costos y rotación separados, fuente confirmada, efectivo insuficiente visible y costos desconocidos pendientes |
| 4 | Cálculo privado por sesión y reportes a demanda | Claves de invalidación, memoria acotada y comprobación de que explorar la pantalla no vuelve a optimizar |
| 5 | Preparación plegada al calcular y resultados por decisiones | Comparación, exposición, meta, evidencia y archivo; importes y probabilidades con formato legible |
| 6 | Comparación de cortes y referencia de seguimiento | Misma cuenta/expediente, orden temporal, variaciones de valuación/peso, referencia y tolerancia declaradas; sin atribuir rendimiento realizado |
| 7 | Exposición directa e indirecta de ETF/fondos | Componentes aportados con fecha/fuente, emisor, sector, país y moneda; cobertura parcial y solapamiento explícitos |
| 8 | Meta ligada a objetivo/horizonte y Monte Carlo | Posiciones más efectivo, aportación o retiro, inflación, costos confirmados, cargos fijos, probabilidad y déficit; gráfico y objetivo en las mismas unidades |

La [guía de uso](account_workflow.md) describe entradas, supuestos y límites de cada función. La entrada principal es **Análisis → Por cuenta**; también hay acceso desde la cuenta en Expedientes.

## Verificación

- Suite completa: **662 pruebas aprobadas en 56.86 segundos**.
- Después del ajuste final de presentación: **3 pruebas de interfaz aprobadas en 20.04 segundos**.
- Ruff: todos los Python versionados y los nuevos módulos/pruebas, sin hallazgos.
- `pip check`: dependencias fijadas en un entorno aislado; sin conflictos.
- `git diff --check`: sin errores de espacios.
- Navegador Edge mediante Playwright: preparación y resultados en **1440, 768 y 390 px**; exposición, meta, generación de PDF, guardado cifrado, reapertura y descarga del PDF archivado. Sin excepciones JavaScript o Streamlit y sin desbordamiento horizontal del documento en las vistas capturadas.
- El inspector de pantallas no registró `FAIL`. Conservó advertencias sobre bordes de controles activos y alineación de la tabla accesible interna de Streamlit. La inspección de las capturas confirma cifras alineadas a la derecha en la tabla visible; no se ocultaron reglas del inspector.

Una ejecución preliminar imprimió un aviso nativo de acceso de memoria de pandas/Arrow en Windows aunque pytest terminó con código 0. No se reprodujo en las repeticiones de interfaz ni en las dos ejecuciones completas posteriores de 662 pruebas. Se registra el antecedente; no se atribuye a una causa demostrada del código.

Las cuentas y los expedientes de verificación fueron ficticios. Las capturas y comprobaciones están en [la carpeta de evidencia](/D:/OptimizacionPortafolio/outputs/app_improvements_2026-11-03/all_passed.json). No se desplegaron cambios ni se consultaron expedientes de producción.

## Límites de esta entrega

La importación no interpreta cualquier PDF o formato GBM: usa el diseño XLSX documentado y el CSV normalizado. Precios, identidad, derechos, tarifas y componentes requieren información comprobada; no se inventa cobertura de proveedores. El libro integral de movimientos, el rendimiento realizado multicuenta y las órdenes con cantidades/lotes son ampliaciones distintas del seguimiento por cortes y de los importes teóricos incorporados aquí.
