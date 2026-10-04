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
  estado (procesada / repetida / sin empleado / inválida / error) y la
  marcación creada. Las de estado *sin empleado* se pueden **Reprocesar**
  (selección + botón) una vez asignado el PIN en el empleado.

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
