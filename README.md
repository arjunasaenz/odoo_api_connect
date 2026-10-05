# api_connect (Odoo 18)

Módulo Odoo que conecta con la API REST de **API Connect**
(https://api-connect.rentipsolution.com) para gestionar terminales de control de
acceso ZKTeco/Hikvision y recibir las marcaciones en `hr.attendance`.

## Instalación (Odoo.sh, Opción A)

1. Conecta este repo a tu proyecto de Odoo.sh:
   **Settings → Repositories → Add repository**, marca el repo y como
   addons path usa la raíz del repo (contiene `api_connect/`).
2. Empuja la rama `odoo` (o el branch de versión que corresponda).
3. En la base de datos: **Apps → API Connect → Instalar**.

## Configuración (menú API Connect → Configuración)

- **URL de API Connect**: `https://api-connect.rentipsolution.com`
- **Usuario / Contraseña**: credenciales de un usuario de API Connect que sea
  dueño de las terminales.
- **Probar conexión**: valida credenciales (login + listado de terminales).
- **Sincronizar terminales**: importa/actualiza el catálogo de terminales.
- **Registrar webhook en API Connect**: publica en la API la URL
  `https://<tu-tenant>.odoo.sh/api_connect/webhook` con el secret generado. A
  partir de ahí cada marcación llega a Odoo en tiempo real.

Si la URL pública de Odoo se detecta mal, se puede fijar con el parámetro de
sistema `api_connect.web_base_url` (Ajustes → Técnico → Parámetros del sistema).

## Uso diario

- **Terminales**: crear en Odoo (nombre, serial, marca, modelo, TZ) →
  *Crear en API Connect*; o sincronizar las ya existentes. El cron de heartbeat
  (cada 15 min) actualiza online/última conexión.
- **Empleados**: en la ficha del empleado (pestaña Ajustes RRHH → grupo
  "API Connect") asigna el **PIN** y las terminales; usa los botones para
  *Registrar en terminales* (alta del usuario en el dispositivo), *Registrar
  tarjeta* (usa el badge del empleado), *Registrar rostro* (envía la foto de la
  ficha al terminal vía biophoto) o *Eliminar de terminales*.
- **Marcaciones**: menú *Marcaciones recibidas* muestra cada evento con su
  estado: *Procesada* (creó/cerró asistencia), *Repetida* (dentro de la ventana
  anti-repetición), *Sin empleado con ese PIN* (asigne el PIN y use
  **Reprocesar**), *Terminal desconocida* (SN no está en Odoo), *Fuera de
  secuencia* (hora del punch anterior al turno abierto; revise el reloj del
  terminal), *Salida suelta* (salida sin turno abierto) o *Inválida / Error*.
  Las de *Sin empleado con ese PIN* se rescatan con el botón **Reprocesar**
  (selección) una vez asignado el PIN.

## Monitoreo (Fase 4)

- Menú **Webhooks fallidos**: espejo local de la cola de reintentos de API
  Connect (`GET /api/webhook-retries/`) con pendientes y dead-letter, intentos,
  códigos HTTP y payload. Botones: *Sincronizar desde API Connect* y
  *Reprocesar seleccionadas* (entrega idempotente a `hr.attendance`, sin
  duplicados gracias a la deduplicación por `ID Event`).
- Botón **Salud Redis** en Configuración → `GET /api/redis/health`.
- El estado online/offline por terminal sigue del cron de heartbeat.

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

## Emparejamiento por grupos

- Cada terminal pertenece a un **grupo** (sincronizado desde API Connect) o al
  **grupo general** (terminales sin grupo).
- Con *Emparejamiento global* desactivado (defecto): un turno abierto solo
  puede cerrarse desde un terminal **del mismo grupo** con el que abrió; un
  punch desde otro grupo se registra como *Terminal de otro grupo* sin tocar
  la asistencia. Con un grupo de un solo terminal, entrada y salida forzosamente
  son de ese dispositivo.
- Con *Emparejamiento global* activado: cualquier terminal abre o cierra
  (comportamiento anterior).
- La asistencia guarda la **terminal de entrada** (campo *Terminal de entrada*
  en hr.attendance) para conocer el grupo propietario del ciclo.

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

## Compatibilidad

Odoo 17/18/19 con ajustes menores (manifest y `type='json'`→`type='jsonrpc'`
en 19). Target principal: **Odoo 18**.

## Pruebas locales (qa_local)

`qa_local/docker-compose.yml` levanta Odoo 18 + PostgreSQL con el addon montado:

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
