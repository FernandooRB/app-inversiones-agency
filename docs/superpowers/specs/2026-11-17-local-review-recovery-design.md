# Copia personal y recuperación de revisiones

Continuación del alcance personal autorizado: USD 0, GBM real sólo local,
formularios/CSV y paquetes portátiles con confirmaciones renovadas.

La pregunta de la pantalla es «¿qué guardé y qué necesito para continuar?».
Conservar la interfaz nativa, tipografía y colores de SIG. Mostrar inventario
legible, libro incluido o borrador, originales por adjuntar y nuevas confirmaciones.
Una vista previa nunca sustituye la revisión vigente. PDF/TXT sólo informan;
el ZIP de movimientos y el de consolidación son recorridos diferentes.

Se evaluaron: disco de Community Cloud (efímero, incompatible con alcance),
ampliar el registro de expedientes (ya existe, requiere configuración e identidad),
y cifrar copias de los ZIP actuales en el equipo. Se elige la tercera como decisión
de implementación: reutiliza Fernet y los lectores acotados existentes, permite
comprobar y recuperar exactamente los bytes sin crear un segundo libro financiero.
No se trasladan claves al navegador ni se configura un servicio nuevo.

Herramienta local: generar clave en archivo nuevo, inspeccionar ZIP, cifrar,
verificar, recuperar ZIP a destino nuevo, cambiar clave a una copia nueva y
eliminar una copia individual sólo con su SHA256 exacto. Retención manual, sin
borrado programado. Clave de recuperación separada; pérdida de clave impide abrir
la copia. El ZIP exportado vuelve a estar sin cifrar. No se promete borrado físico
de SSD ni de otras copias. No se migran originales ni archivos reales existentes.

Los lectores actuales de movimientos v1–v5 y consolidación v1 siguen siendo la
autoridad. Exigir el contexto explícito para paquetes ligados a expediente/cuenta;
no inferir autorización de un manifiesto. Ninguna aprobación queda guardada.
Límites: ZIP15MB; token cifrado21MB; clave Fernet44bytes; archivos regulares y
sin enlaces/junctions en su ruta, escritura exclusiva a destino nuevo.

Accesibilidad: controles nativos con etiquetas visibles, inventario textual,
instrucciones junto al botón, foco/teclado y capturas1440/768/390. axe automatizado
no reemplaza lector de pantalla ni prueba humana en Samsung S23/Chrome.

Cierre: pruebas hostiles, ciclo guardar/cerrar/reabrir/cambiar clave/eliminar,
regresión Windows/Linux, navegador, dependencias, cálculos existentes, contenedor,
reportes y comprobación publicada ficticia. Registrar pendientes por separado.
