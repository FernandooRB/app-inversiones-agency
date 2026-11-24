# Continuar una revisión y conservar copias personales

En **Movimientos → Abrir paquete de movimientos** elige el ZIP completo, sin
extraerlo. La vista previa muestra el corte, moneda e inventario. «Libro incluido»
significa que se guardó el CSV del libro; todavía debes revisar sus datos.
«Borrador sin libro» conserva las correcciones GBM pero aún requiere preparar el
libro. PDF/TXT sirven para consultar y no sustituyen el ZIP.

La vista previa conserva la revisión actual. Sólo «Retomar movimientos» o
«Reemplazar revisión con este paquete» aplica el paquete y renueva confirmaciones.
Un ZIP inválido conserva los insumos actuales. Los formatos movimientos1–5 siguen
legibles. El ZIP de varias cuentas se abre en **Patrimonio → Consolidar libros
revisados** y usa un formato independiente. Los originales PDF/XML se adjuntan de
nuevo cuando se requiere cotejo; no están en los paquetes portátiles.

## Copia cifrada local opcional

Esta herramienta funciona en tu computadora, desde la carpeta del repositorio con
su entorno Python. No usa la web ni configura almacenamiento en Community Cloud.
No modifica tu expediente, originales, cálculos ni archivo de origen. La copia
conserva exactamente el ZIP y lo valida antes de cifrar y después de descifrar.

Ejemplo PowerShell con rutas nuevas, privadas y sin sincronización pública:

```powershell
.\.venv\Scripts\python.exe -m scripts.local_review keygen --destination 'D:\RutaPrivada\clave.sigkey'
.\.venv\Scripts\python.exe -m scripts.local_review inspect --source 'D:\RutaPrivada\revision.zip'
.\.venv\Scripts\python.exe -m scripts.local_review save --source 'D:\RutaPrivada\revision.zip' --key-file 'D:\RutaPrivada\clave.sigkey' --destination 'D:\CopiasPrivadas\revision.siglocal'
.\.venv\Scripts\python.exe -m scripts.local_review verify --source 'D:\CopiasPrivadas\revision.siglocal' --key-file 'D:\RutaPrivada\clave.sigkey'
.\.venv\Scripts\python.exe -m scripts.local_review restore --source 'D:\CopiasPrivadas\revision.siglocal' --key-file 'D:\RutaPrivada\clave.sigkey' --destination 'D:\RutaPrivada\recuperado.zip'
```

Sustituye las rutas; las carpetas padre deben existir. En Linux usa `.venv/bin/python`.
Nunca se sobrescribe un archivo. Para paquetes ligados añade `--case-id ID`
y `--account-id ID`; para consolidación ligada, `--case-id ID` y un
`--allowed-account ID` por cuenta autorizada. Estos parámetros conservan el ámbito;
no crean permisos ni vinculan automáticamente un paquete temporal a un expediente.

Abre el ZIP recuperado en la app local y revisa de nuevo las fuentes/confirmaciones.
`verify` comprueba formato, huellas y contexto; no certifica importes ni documentos.
Las salidas de comandos no muestran fuentes, saldos, identificadores de cuenta,
claves ni rutas de archivos; muestran estados, tamaños, corte e inventario.

## Claves y retención

La clave aleatoria Fernet se guarda en el archivo elegido y nunca se introduce en
la app. Consérvala separada de las copias, con recuperación en otro lugar protegido.
Quien tenga la clave puede leer y crear copias válidas; perderla impide recuperar
el contenido. Se reutiliza [Fernet de cryptography](https://cryptography.io/en/stable/fernet/),
ya instalado. Su token revela la hora de cifrado y el tamaño aproximado. No es
cifrado completo del disco. En Windows los permisos0600 no sustituyen ACL NTFS;
protege ambas carpetas y sus copias con los permisos y cifrado de tu equipo.

Retención manual: conserva una copia anterior hasta verificar y abrir la nueva.
Para cambiar de clave, genera otra en un destino nuevo y ejecuta:

```text
python -m scripts.local_review rotate --source copia.siglocal --key-file clave.sigkey --new-key-file nueva.sigkey --destination nueva.siglocal
```

Comprueba la copia nueva con la clave nueva. El archivo anterior sigue requiriendo
la clave anterior; no se eliminan automáticamente claves ni respaldos previos.
Seleccionar dos archivos con el mismo material de clave se rechaza.
Para eliminar una copia individual ya verificada, toma `encrypted_sha256` de
`verify` y pásalo completo:

```text
python -m scripts.local_review delete --source copia.siglocal --key-file clave.sigkey --confirmation-sha256 SHA256_COMPLETO
```

Esta eliminación afecta sólo a ese archivo, no al ZIP de origen, claves, otras
copias ni respaldos del sistema; no acredita borrado físico de SSD. El ZIP
recuperado vuelve a estar sin cifrar. No hay borrado automático por antigüedad.

## Límites y auditoría

ZIP hasta15MB, token hasta21MB y clave44bytes. Los lectores internos mantienen sus
límites más estrictos. Archivos regulares; se rechazan enlaces/junctions en la
ruta y destinos existentes. No se leen rutas ni módulos declarados por el ZIP.
La representación Base64 del token debe ser canónica: una edición, incluso un
espacio añadido, se rechaza. Las escrituras y eliminaciones de esta herramienta
coordinan el nombre mediante un archivo `.siglock`; una operación concurrente
sobre ese destino se rechaza. Si se interrumpe el proceso y queda un bloqueo,
detén los procesos de copia y comprueba que no haya una operación activa antes
de retirar manualmente sólo ese archivo de bloqueo. Nunca se retira por antigüedad.
El operador local debe controlar la carpeta y evitar que terceros la modifiquen
durante una operación. No es un servicio multiusuario ni un sustituto de las
autorizaciones OIDC del registro de expedientes.

Pruebas ficticias: errores de clave, corrupción, contexto ajeno, límites, enlaces,
colisiones, recuperación en proceso nuevo, rotación y borrado explícito. El
navegador comprueba vista previa, teclado, ZIP inválido, confirmaciones renovadas
y anchos1440/768/390 con axe. La auditoría de cada entrega registra por separado
automatización, revisión visual y prueba humana/física. Permanecen pendientes
lector de pantalla y uso humano de este recorrido. Alojamiento USD0.
