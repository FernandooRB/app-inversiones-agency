# Expedientes, revisión y operación interna

## Alcance de esta versión

El registro conserva alias de expedientes, perfil declarado, cuentas, evidencias, archivos y
revisiones. Usa SQLite con contenido cifrado y una clave Fernet distinta por expediente, protegida
por una clave maestra externa. Los originales del piloto existente no se han migrado ni se ha
habilitado almacenamiento de clientes en producción.

Los identificadores, conteos, tamaños aproximados y tiempos de los tokens pueden ser observables
en el archivo. No es cifrado de disco completo ni sustituye ACL, protección del equipo, TLS,
resguardo de la clave y auditoría independiente. La documentación de
[Fernet](https://cryptography.io/en/stable/fernet/) explica que quien posee la clave puede leer y
crear mensajes válidos; perderla impide recuperar el contenido.

## Preparación por administración

1. Seleccionar almacenamiento privado persistente. No usar un disco efímero del hosting ni una
   carpeta pública. En Windows verificar BitLocker o protección equivalente y permisos NTFS; en
   otros entornos comprobar cifrado y permisos equivalentes. Estas condiciones no se infieren de Git.
2. Custodiar una clave Fernet generada mediante la biblioteca en el gestor de secretos autorizado.
   No pegarla en el chat, el repositorio, argumentos de comandos, logs o los documentos de cuenta.
   Conservar recuperación de la clave por separado de los respaldos.
3. Completar los campos de `[workspace]` del ejemplo de secretos en el gestor del entorno final;
   la configuración pública permanece desactivada. Nunca subir el archivo real a Git.
4. Para cada identidad OIDC autorizada, establecer un único rol explícito. `ADMIN` administra y ve
   todos los expedientes; `ANALYST` crea y edita los asignados; `REVIEWER` lee y registra revisiones
   en los asignados; `VIEWER` sólo consulta los asignados. La identidad sigue siendo emisor y sujeto,
   no el correo electrónico. Revocar una identidad global exige actualizar la política del servidor.
5. Ingresar con administración e inicializar el registro nuevo desde Expedientes. No se sobrescribe
   una base existente. Probar con datos sintéticos antes de habilitar datos autorizados.

## Recorrido del equipo

1. Crear un expediente con alias, sin nombre, número de contrato, RFC o domicilio. Conservar la
   vinculación con la persona en el sistema de identidad autorizado, separado de este registro.
2. Añadir intermediario, producto y cartera/subcuenta. Ejemplo conceptual: GBM → Trading MX → BMV.
   Registrar otra cartera crea metadatos internos: no abre una cuenta real en GBM.
3. Recabar objetivo, horizonte, liquidez, capacidad y tolerancia a pérdidas, experiencia y
   restricciones. Los valores iniciales de un formulario no constituyen respuestas del titular.
   Confirmar la entrevista antes de guardar. No se deriva idoneidad automáticamente.
4. Registrar evidencia por control, su referencia, huella y fecha; declarar vencimiento cuando
   corresponda. Este paso no autentica documentos ni reemplaza su cotejo. Guardar los originales
   cifrados en Archivos si corresponde al alcance y permiso del expediente.
5. Ejecutar Análisis. Al final, seleccionar el expediente y la cuenta de destino, comprobar su
   correspondencia y guardar el paquete interno: PDF y manifiesto con parámetros, asignaciones,
   fechas efectivas y huella del reporte. No incluye los precios crudos del proveedor.
6. Asignar revisores desde Administración. Dos personas distintas de la última que editó contenido
   registran sus conclusiones para la versión vigente. Los cambios de perfil, evidencia, archivos o acceso
   incrementan la versión y dejan obsoletas las revisiones anteriores. La revisión interna nunca
   modifica `client_delivery_allowed`, que permanece falso.
   Un cambio de permisos no sustituye la identidad de quien editó el contenido financiero.
7. Consultar y exportar el historial sólo a un destino privado. La descarga contiene datos del
   expediente descifrados y requiere la misma protección que cualquier exportación financiera.

## Respaldo y recuperación

Los comandos son para un operador local de confianza que ya posee la clave; no son un endpoint
OIDC y no deben publicarse como servicio web. El administrador provee `SIG_CASE_STORE_KEY` mediante
el gestor de secretos o el entorno de un proceso protegido, sin mostrar su valor.

```powershell
.venv\Scripts\python.exe scripts/workspace_operations.py --database data/private/workspace/cases.db check
.venv\Scripts\python.exe scripts/workspace_operations.py --database data/private/workspace/cases.db backup --destination data/private/workspace/respaldo_nuevo.db
.venv\Scripts\python.exe scripts/workspace_operations.py --database data/private/workspace/cases.db restore --source data/private/workspace/respaldo_nuevo.db --destination data/private/workspace/recuperado_nuevo.db
```

Las carpetas de destino deben existir y los archivos ser nuevos. Se utiliza la
[API de respaldo consistente de SQLite](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup).
La recuperación comprueba estructura, cadena de integridad, versiones y archivos cifrados. Nunca
sobrescribe una base en uso. Antes de cambiar a una base recuperada, detener escrituras, comprobar
el punto temporal recuperado, las altas/revocaciones y las bajas posteriores al respaldo.

Administración debe definir frecuencia, retención, responsables y tiempos de recuperación según
el servicio. No se ha programado un respaldo del equipo real ni probado todavía en el hosting final.
La clave no se rota automáticamente: cambiarla sin un procedimiento de migración dejaría la base
ilegible. No confundir comprobación estructural con recuperación operativa del servicio completo.

## Archivo, baja y límites del historial

Archivar impide nuevas ediciones del analista y conserva la consulta; administración puede recuperar
el expediente archivado. La eliminación definitiva es un comando separado, exige estado archivado
y confirmación del alias exacto. No se ha ejecutado contra ningún expediente real.

La eliminación retira el expediente, sus archivos y su clave individual de la base viva; queda una
constancia de baja y eventos cifrados sin esa clave. Los respaldos anteriores conservan material
recuperable: deben tratarse conforme al plazo aprobado y no restaurar bajas sin control. No se
garantiza borrado forense de SSD, temporales, exportaciones o copias externas.

La cadena HMAC detecta alteraciones y discrepancias con el inventario, pero no demuestra que un
administrador que posee la clave sea independiente ni detecta por sí sola la reversión completa
a una copia antigua válida. Para producción falta anclaje externo del historial, monitoreo,
custodia de claves y auditoría de acceso del entorno definitivo. No equivale a una firma electrónica.

## Comprobaciones de aceptación del entorno final

- Acceso válido, identidad no asignada, sesión vencida, revocación y cierre de sesión.
- Un expediente inaccesible para otro analista y permisos separados de revisión/edición.
- Rechazo de edición obsoleta y de autorrevisión; cambio de versión tras un nuevo archivo.
- Guardado y descarga del paquete correcto por cuenta; exportaciones fuera de sitios públicos.
- Respaldo a almacenamiento protegido y recuperación a una ruta nueva con clave custodiada.
- Conservación y baja coordinadas con respaldos y sistemas externos.
- Sin claves ni información financiera en logs, Git, CI o herramientas de soporte.

Las pruebas automatizadas usan datos sintéticos. El resultado local no aprueba este entorno final.
