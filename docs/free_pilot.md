# Piloto gratuito

Destino actual: **Streamlit Community Cloud**, con presupuesto de alojamiento **USD 0**.
La aplicación continúa siendo Streamlit; no requiere reescribir la interfaz ni
contratar Render. `render.yaml` permanece como referencia de pago para otra etapa.

## Estado comprobado el 8 de noviembre de 2026

La aplicación existente está activa en
[app-inversiones-agency.streamlit.app](https://app-inversiones-agency.streamlit.app/),
con Python 3.12 y acceso mediante Google. Se comprobó el análisis de una cartera
ficticia, descarga de PDF/ZIP, integridad del paquete y reapertura con resultados y
PDF archivado. Un navegador sin sesión no tuvo acceso al análisis. No se probó otra
identidad Google ni se subieron estados de cuenta reales para esta comprobación.

Se conservaron la configuración de acceso y el backend externo de Seguimiento.
Expedientes en disco temporal y operaciones programadas permanecen desactivados.
No se contrataron servicios de pago. La comprobación no cambia los pendientes de
revisión del piloto GBM propio ni habilita entrega de reportes a clientes.

## Alcance

| Función | Piloto web gratuito | App en tu equipo |
| --- | --- | --- |
| Análisis de cartera, costos, metas, escenarios y reportes | Disponible por sesión | Disponible |
| Retomar insumos y resultados | Descargar/abrir paquete ZIP | ZIP o expediente configurado |
| Revisión de PDF/XML y operaciones por archivos | Disponible por sesión | Disponible |
| Expedientes, borradores y auditoría permanentes | Desactivados en disco temporal | Disponibles con registro cifrado |
| Seguimiento y bitácoras guardadas | Requieren base externa | Disponibles con SQLite local |
| Revisiones programadas y respaldos de servidor | Desactivados | Requieren ejecutar el trabajador configurado |

Community Cloud no garantiza persistencia del almacenamiento local. El perfil
`session_only` impide abrir expedientes en ese disco, incluso si se copia por error
una configuración con `workspace.enabled=true`. También bloquea el seguimiento con
SQLite temporal; se puede habilitar después con el backend externo ya soportado.
No convierte el contenido del expediente en almacenamiento permanente en la nube.

Descarga el paquete del análisis al terminar. Consérvalo como el documento original,
porque incluye insumos privados. Puede reabrirse con **Retomar paquete**. Una sesión
o un archivo temporal del servidor puede desaparecer al reiniciar o cerrar la app.

## Publicación

1. Entrar a [Streamlit Community Cloud](https://share.streamlit.io/) y vincular GitHub.
2. Elegir **Create app**, repositorio `FernandooRB/app-inversiones-agency`, rama `main`
   y archivo `app_inversiones.py`. Usar Python 3.12, la versión validada del proyecto.
3. En **Advanced settings > Secrets**, usar `.streamlit/secrets.free.example.toml`
   como estructura. Los valores reales van en ese gestor, nunca en el repositorio.
4. Configurar el cliente de Google para la URL real asignada a la app, con callback
   `https://<host-real>.streamlit.app/oauth2callback`. Mantener las identidades
   permitidas mediante emisor y `sub` verificado, igual que en la app local.
5. Comprobar login, rechazo de otra identidad, análisis con datos ficticios, descarga
   del ZIP, reapertura y logout antes de cargar documentos propios.

El proyecto incluye las dependencias de producción en `requirements.txt`. Community
Cloud ejecuta directamente `app_inversiones.py`; no utiliza el arranque de Docker
que exige un disco persistente. No ejecutar el trabajador como proceso permanente
en el piloto gratuito.

La publicación requiere una cuenta de Community Cloud vinculada al repositorio y
configurar el cliente Google. La conexión de GitHub en Codex no inicia esa sesión
en Community Cloud ni crea automáticamente el cliente OAuth de la app.

## Límites y siguiente etapa

Community Cloud puede suspender una app inactiva y sus recursos son compartidos.
No se promete disponibilidad continua ni capacidad ilimitada. Si se alcanza un
límite, reducir el cálculo o continuar localmente; no activar un plan de pago sin
una nueva autorización.

Para habilitar persistencia externa hay que adaptar y verificar el registro de
expedientes, sus archivos y auditoría; conectar sólo una lista de seguimiento no
resuelve el almacenamiento de toda la aplicación. Esa migración no se presenta
como ya realizada. Mientras tanto, el registro completo se conserva en tu equipo.

Fuentes oficiales:

- [Servicio gratuito y conexión con GitHub](https://docs.streamlit.io/deploy/streamlit-community-cloud).
- [Publicación, Python y secretos](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).
- [Persistencia de archivos locales](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).
- [Límites e hibernación](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).
