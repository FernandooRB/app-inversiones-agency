# Criterios de la interfaz interna

El trabajo sigue la guía de pantallas operativas, estilo `achromatic-ledger`, semilla 1448053148.
No se redibujó la marca del sitio público ni se sustituyó el stack Streamlit. Se conservó la
tipografía nativa ya cargada. La identidad visible usa SIG y el nombre completo; azul sólo en
datos y una marca pequeña, controles neutros y cifras tabulares. No se inventaron métricas de negocio.

Inventario: expediente con alias; intermediario/producto/cartera; perfil declarado en meses,
MXN y porcentajes; documentos con huellas; versiones; evidencias pendientes; revisiones por
persona y versión; alternativas financieras; gráficos y PDF internos; respaldo y baja.

Las preguntas de cada área son:

- Análisis: qué alternativas matemáticas produce el mismo universo bajo los mismos supuestos.
  Los resultados preceden a los detalles de evidencia, que se abren cuando hay alertas de precios.
- Seguimiento: qué acciones tienen confirmación de precio, volumen e impulso y qué condiciones
  faltan. La lista conduce al gráfico de cuatro paneles, las reglas y el plan de referencia.
  Conserva `achromatic-ledger` y sus colores; el motivo propio es la evidencia junto a cada señal.
- Expedientes: qué cuenta se está estudiando y qué falta revisar. Cuentas y perfil comparten
  la primera vista; los formularios de actualización se abren cuando corresponde.
- Evidencia: qué documentos se declararon, con su alcance y pendientes, sin llamarlos auténticos
  por coincidencia de una huella.
- Guía operativa: cuál es el siguiente paso del equipo y qué evidencia necesita.

El análisis conserva la barra nativa de parámetros porque se usa durante sesiones de investigación;
los expedientes usan navegación superior y columnas que se apilan en móvil. El motivo propio del
producto es la revisión por cuenta y versión, visible junto al alias y sus pendientes.

Las capturas de desarrollo usan un expediente y series sintéticos, con aviso explícito. No son
una cuenta real ni una fuente de mercado. Se revisan escritorio, tableta y móvil. El comprobador
estático se aplica al CSS extraído de `workspace_presentation.py`, porque no admite Python.
El lanzador CDP de la guía no inició en este Windows; se ejecutan sus mismos módulos de medición
y reglas mediante Playwright, además de la revisión visual de las capturas y pruebas de interfaz.

El trabajo local no certifica accesibilidad integral, seguridad ni funcionamiento en el hosting
definitivo. La navegación, el recorrido por el equipo y los controles de sesión también deben
validarse en ese entorno con identidades autorizadas y usuarios de prueba.
