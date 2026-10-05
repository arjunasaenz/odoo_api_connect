# API Connect — Módulo Odoo (Odoo 18)

Módulo Odoo **oficial** que conecta con la API REST de **API Connect**
(https://api-connect.rentipsolution.com) para gestionar terminales de control
de acceso **ZKTeco / Hikvision** desde Odoo y recibir las **marcaciones en
tiempo real** en `hr.attendance`.

- Repositorio: https://github.com/arjunasaenz/odoo_api_connect
- Versión del módulo: `18.0.4.0.0` (compatible Odoo 17/18/19)
- Licencia: LGPL-3 · Categoría: Human Resources/Connectors
- Depende de: `hr`, `hr_attendance` (apps nativas de Odoo)

---

## Requisitos

| Hosting de Odoo | Soporte |
|---|---|
| **Odoo.sh** | ✅ Soportado (recomendado) |
| **Self-hosted** (Docker / VPS) | ✅ Soportado |
| **Odoo Online** (odoo.com SaaS) | ❌ No soportado: Odoo Online no acepta módulos con código Python. Alternativas: migrar a Odoo.sh (contáctalos con tu CSM) o usar API Connect directo |

Además necesitas una **cuenta de API Connect** con las terminales asignadas
que usará el conector (el usuario configurado en Odoo debe ser dueño de las
terminales que quieres gestionar).

## Instalación

### Odoo.sh

1. En tu proyecto de Odoo.sh: **Settings → Repositories → Add repository** →
   agrega `arjunasaenz/odoo_api_connect` y selecciona la rama `odoo`
   (addons path = la raíz del repo, contiene `api_connect/`).
2. Espera el build → en tu base de datos: **Apps → API Connect → Activar**
   (instala también Empleados y Asistencia si faltan).
3. Configura (siguiente sección) y listo.

### Self-hosted (Docker / VPS)

1. Descarga el zip del release más reciente
   (`https://github.com/arjunasaenz/odoo_api_connect/releases`) o clona el repo.
2. Copia la carpeta `api_connect/` dentro de tu addons-path.
3. **Apps → Update Apps List → API Connect → Activar**.
4. Configura (siguiente sección).

### Actualizaciones

Al publicarse una nueva versión (manifest `version`), Odoo.sh y los builds
self-hosted con `-u api_connect` ejecutan el upgrade automáticamente
(vistas, security y migraciones de datos incluidas).

## Configuración (menú API Connect → Configuración)

1. **URL de API Connect**: por defecto `https://api-connect.rentipsolution.com`.
2. **Usuario / Contraseña**: credenciales de tu cuenta de API Connect (dueña
   de las terminales) → **Guardar** → **Probar conexión**.
3. **Sincronizar terminales**: importa terminales y grupos de terminales.
4. **Registrar webhook en API Connect**: publica la URL
   `https://<tu-tenant>.odoo.sh/api_connect/webhook` con el secret generado →
   las marcaciones llegan a Odoo en tiempo real.

Troubleshooting rápido:

| Síntoma | Causa típica |
|---|---|
| "Login fallido (400)" | Usuario/contraseña de API Connect incorrectos |
| "Terminal offline/expired" al enviar comandos | El dispositivo no se ha conectado recientemente (ver *En línea / Última conexión* en la ficha) |
| Webhook no llega / 401 | Rotaste el secret → *Registrar webhook* de nuevo; o `web.base.url` mal detectado → fija el parámetro de sistema `api_connect.web_base_url` |
| Marcaciones "Terminal de otro grupo" | El punch llegó de una terminal de otro grupo que el grupo que abrió el turno |

## Uso diario

- **Terminales**: crear en Odoo (nombre, serial, marca, modelo, TZ) →
  *Crear en API Connect*; o sincronizar las existentes. Cron de heartbeat
  (15 min) actualiza estado online/última conexión.
- **Empleados**: ficha del empleado → pestaña *Ajustes* → grupo
  **API Connect**: asigna el **PIN** (igual al del terminal), las terminales y
  usa los botones: registrar/actualizar en terminales, tarjeta (badge),
  rostro con foto, huella, biodata, selfie por email, expiración y renovación,
  grupo de acceso, baja.
- **Operaciones masivas**: lista de Empleados → menú *Acción* →
  *API Connect: Alta masiva en terminales* / *Baja masiva de terminales*.
- **Marcaciones**: menú *Marcaciones recibidas* — cada punch con su estado
  (procesada, repetida, sin empleado con ese PIN, terminal desconocida, fuera
  de secuencia, salida suelta, inválida, error) y la asistencia generada.
- **Horarios de acceso / Feriados / Visitantes**: pestañas de la ficha de
  terminal.
- **Webhooks fallidos**: menú con la cola de reintentos de API Connect
  (pendientes y dead-letter) + reprocesar con un clic.

## Funcionalidades completas

Ver secciones detalladas abajo: [Gestión de terminales](#gestión-de-terminales-fase-1),
[Horarios, feriados y visitantes](#horarios-feriados-y-visitantes-fase-2),
[Empleados avanzados](#empleados-avanzados-fase-3),
[Monitoreo](#monitoreo-fase-4), [Emparejamiento por grupos](#emparejamiento-por-grupos),
[Anti-repetición](#anti-repetición).

## Gestión de terminales (Fase 1)

Desde la ficha de cada terminal (menú *Terminales*): **Actualizar en API**,
**Refrescar parámetros** (tipo de equipo, nº de puertas/lectores, parámetros
crudos), **Desbloquear (5 s)**, **Sincronizar hora**, **Enviar mensaje**
(público o privado por PIN), **Wiegand** (definir/borrar formato),
**Restaurar fábrica**, **Reiniciar**, **Borrar logs**, **Borrar TODOS los
datos** (destructivos con confirmación, solo administrador), **Reset de
acceso** y **Fábrica de puertas** (solo Hikvision).

Cada comando queda en el log (pestaña *Comandos*) con la respuesta del
dispositivo consultable vía *Consultar respuestas del dispositivo (hoy)*.

**Puertas**: al refrescar parámetros se generan las N puertas del panel
(una fila por puerta con nombre editable). Cada puerta tiene *Abrir* y
*Configurar* (settings de puerta por marca: ZK `door/set_parameters`,
HK `acc/access/door_settings`).

**Grupos de terminales**: bidireccionales — se sincronizan desde la API y se
pueden crear/renombrar/eliminar en la API desde Odoo (la creación incluye las
terminales asignadas; agregar terminales a un grupo existente se hace desde la
ficha de terminal vía la API; quitar no está soportado por la API).

## Horarios, feriados y visitantes (Fase 2)

- **Horarios de acceso** (pestaña *Horarios de acceso* de la terminal):
  7 días × 3 periodos. ZKTeco usa `access/access_time` (periodo 1 obligatorio,
  vacío = `00:00` = sin ventana), Hikvision usa `acc/access/access_time`
  (formato HHMM; el primer envío es POST y los siguientes PUT).
- **Feriados** (pestaña *Feriados*): ZK requiere nº + nombre + MM-DD; HK usa
  `holiday_access_date`/`holiday_type`/`holiday_loop`. Borrado de horarios
  solo soportado para ZKTeco (la API no lo expone para HK).
- **Grupo de acceso ZK** (botón en la pestaña): `access_group_id` + opcionales
  holiday/tz_format → `access/access_group`.
- **Visitantes** (botón en la pestaña): alta en terminales seleccionadas con
  PIN, QR (autogenerado), tipo, ventana de acceso, puertas y nº de
  verificaciones → `visitor/{sn}`.

## Empleados avanzados (Fase 3)

En la ficha del empleado: **Actualizar en terminales** (PUT con nombre/tarjeta/
expiración), **Expira en terminales** (fecha opcional) + **Renovar expiración**,
**Registrar huella** y **Biodata** (wizards con subida de plantilla binaria,
base64 automática), **Borrar tarjeta**/**Borrar rostro**, **Invitar a selfie**
(usa el email de trabajo y las terminales del empleado) y **Grupo de acceso**
(wizard por empleado).

En la **lista de empleados** (menú Acción, solo administrador):
*API Connect: Alta masiva en terminales* y *Baja masiva de terminales*
(una llamada `bulk` por terminal, lotes de 300, máximo 3000 por llamada).

## Monitoreo (Fase 4)

- Menú **Webhooks fallidos**: espejo local de la cola de reintentos de API
  Connect (`GET /api/webhook-retries/`) con pendientes y dead-letter, intentos,
  códigos HTTP y payload. Botones: *Sincronizar desde API Connect* y
  *Reprocesar seleccionadas* (entrega idempotente a `hr.attendance`, sin
  duplicados gracias a la deduplicación por `ID Event`).
- Botón **Salud Redis** en Configuración → `GET /api/redis/health`.
- El estado online/offline por terminal sigue del cron de heartbeat.

## Emparejamiento por grupos

- Cada terminal pertenece a un **grupo** (sincronizado desde API Connect) o al
  **grupo general** (terminales sin grupo).
- Con *Emparejamiento global* desactivado (defecto): un turno abierto solo
  puede cerrarse desde un terminal **del mismo grupo** con el que abrió; un
  punch desde otro grupo se registra como *Terminal de otro grupo* sin tocar
  la asistencia. Con un grupo de un solo terminal, entrada y salida forzosamente
  son de ese dispositivo.
- Con *Emparejamiento global* activado: cualquier terminal abre o cierra.
- La asistencia guarda la **terminal de entrada** para conocer el grupo
  propietario del ciclo.

## Anti-repetición

En *Configuración → Marcaciones* existe **Ventana anti-repetición (min)**:
marcaciones del mismo empleado dentro de esa ventana se marcan como
*Repetida* y no generan asistencia. Acepta fracciones (0.5 = 30 segundos).
0 desactiva el control. La ventana se aplica también al reprocesar.

## Webhook

`POST /api_connect/webhook` (auth por `Authorization: Bearer <webhook_secret>`).

Es idempotente: deduplica por `ID Event` (si la API reintenta una marcación,
no se duplica la asistencia). Los pines sin empleado asignado se registran con
estado *sin empleado* y responden 200 para evitar bucles de reintentos.

## Seguridad

- El webhook exige `Authorization: Bearer <webhook_secret>` (comparación
  timing-safe). Puedes **rotar el secret** desde Configuración
  (*Rotar secret* → *Registrar webhook* de nuevo); se recomienda rotarlo
  periódicamente (por ejemplo cada 90 días).
- Los comandos de apertura de puerta están disponibles para **cualquier
  usuario del conector** (decisión de producto). Las acciones destructivas
  (reiniciar, borrar logs, borrar todos los datos, restaurar fábrica, reset de
  acceso, eliminar grupos) están limitadas al grupo *Administrador API
  Connect* y piden confirmación.
- La contraseña de API Connect se almacena en la base de datos de Odoo con
  acceso restringido al grupo *Administrador API Connect* (patrón estándar de
  configuraciones Odoo).
- Los punches simultáneos de una misma persona se procesan de forma
  serializada (lock por PIN) para evitar carreras.

## Compatibilidad

Odoo 17/18/19 con ajustes menores (manifest y `type='json'`→`type='jsonrpc'`
en 19). Target principal: **Odoo 18** en Odoo.sh.

## Pruebas locales (qa_local)

`qa_local/docker-compose.yml` levanta un Odoo 18 + PostgreSQL **de pruebas
locales** con el addon montado. ⚠️ Contiene credenciales de ejemplo
(`admin/admin`, master `admin`) — es un rig de desarrollo, **no usar tal cual
en producción** ni exponerlo a internet:

```bash
cd qa_local
docker compose up -d
```

- URL: http://localhost:8069 — BD `apiconnect` — admin/admin
- El módulo se instala por la UI: Apps → Update Apps List → API Connect → Activar
- En *Configuración*, para apuntar a una API Connect corriendo en el host
  Windows (dev, puerto 8777), usar `http://host.docker.internal:8777`
  (dentro del contenedor `localhost` es el propio contenedor).
- El webhook sale como `http://localhost:8069/api_connect/webhook`, alcanzable
  desde la API corriendo en el host.

## Notas

- El PIN del empleado debe ser único en Odoo (constraint) y coincidir con el
  PIN configurado en el terminal.
- Las terminales Hikvision requieren Device ID / Device Key para crearse.
- El módulo no incluye secretos ni credenciales: todo se configura en la base
  de datos tras la instalación.
