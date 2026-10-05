import json
import logging
from datetime import timedelta

import pytz
from dateutil import parser as dateutil_parser
from odoo import _, api, fields, models
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)

ONLINE_WINDOW_MINUTES = 15


def _parse_date(value):
    if not value:
        return False
    if isinstance(value, str):
        try:
            return dateutil_parser.isoparse(value).date()
        except (ValueError, TypeError):
            return False
    return value


class ApiConnectTerminalGroup(models.Model):
    _name = "api.connect.terminal.group"
    _description = "API Connect - Grupo de terminales"
    _order = "name"

    name = fields.Char(string="Nombre", required=True)
    api_id = fields.Char(string="ID en API Connect", readonly=True, copy=False, index=True)
    description = fields.Char(string="Descripción")
    color_code = fields.Char(
        string="Color",
        default="blue",
        help="Código de color tal como lo usa API Connect (blue, red, green...)",
    )
    terminal_ids = fields.One2many("api.connect.terminal", "group_id", string="Terminales")

    _sql_constraints = [
        ("api_id_uniq", "unique(api_id)", "El grupo ya está sincronizado"),
    ]

    def action_create_in_api(self):
        client = self.env["api.connect.config"].get_client()
        for group in self:
            if group.api_id:
                raise UserError(_("El grupo %s ya existe en API Connect") % group.name)
            data = client.create_group({
                "name": group.name,
                "description": group.description or None,
                "color_code": group.color_code or "blue",
                "terminal_serials": group.terminal_ids.mapped("sn"),
            })
            group.write({"api_id": str(data.get("id") or "")})
        return self.env["api.connect.config"]._notify(_("Grupos creados en API Connect"))

    def action_update_in_api(self):
        client = self.env["api.connect.config"].get_client()
        for group in self:
            if not group.api_id:
                raise UserError(
                    _("Cree primero el grupo %s en API Connect") % group.name
                )
            client.update_group(group.api_id, {
                "name": group.name,
                "description": group.description or None,
                "color_code": group.color_code or "blue",
            })
        return self.env["api.connect.config"]._notify(_("Grupos actualizados en API Connect"))

    def action_delete_from_api(self):
        client = self.env["api.connect.config"].get_client()
        for group in self:
            if group.api_id:
                client.delete_group(group.api_id)
            group.terminal_ids.write({"group_id": False, "api_group_id": False})
            group.unlink()
        return self.env["api.connect.config"]._notify(
            _("Grupos eliminados (también en API Connect)"), "warning"
        )


class ApiConnectTerminalDoor(models.Model):
    _name = "api.connect.terminal.door"
    _description = "API Connect - Puerta de terminal"
    _order = "terminal_id, door_number"

    terminal_id = fields.Many2one(
        "api.connect.terminal", string="Terminal", required=True, ondelete="cascade"
    )
    door_number = fields.Integer(string="Número de puerta", required=True)
    name = fields.Char(string="Nombre de la puerta", required=True)
    open_time = fields.Integer(string="Segundos abierta", default=5)

    _sql_constraints = [
        (
            "door_uniq",
            "unique(terminal_id, door_number)",
            "Puerta duplicada en la terminal",
        ),
    ]

    def action_open_door(self):
        for door in self:
            if door.terminal_id.brand == "HK":
                call = lambda c, d=door: c.hk_open_door(
                    d.terminal_id.sn, [d.door_number], d.open_time
                )
            else:
                call = lambda c, d=door: c.open_door(
                    d.terminal_id.sn, [d.door_number], d.open_time
                )
            door.terminal_id._call_api_logged(
                _("Abrir puerta %s") % door.door_number, call
            )
        return self.env["api.connect.config"]._notify(_("Apertura enviada"))

    def action_open_door_settings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "api.connect.door.settings.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_terminal_id": self.terminal_id.id,
                "default_door_number": self.door_number,
            },
        }


class ApiConnectTerminal(models.Model):
    _name = "api.connect.terminal"
    _description = "API Connect - Terminal"
    _order = "name"

    name = fields.Char(string="Nombre", required=True)
    sn = fields.Char(string="Número de serie", required=True, index=True)
    model = fields.Char(string="Modelo")
    brand = fields.Selection(
        [("ZK", "ZKTeco"), ("HK", "Hikvision")],
        string="Marca",
        default="ZK",
        required=True,
    )
    tz = fields.Char(string="Zona horaria")
    group_id = fields.Many2one(
        "api.connect.terminal.group",
        string="Grupo de terminales",
        help="Terminales del mismo grupo comparten el ciclo de entrada/salida. "
             "Sin grupo quedan en el grupo general.",
    )
    api_group_id = fields.Char(
        string="Grupo en API Connect",
        readonly=True,
        copy=False,
        index=True,
        help="UUID del grupo tal como viene de la API",
    )
    api_id = fields.Char(string="ID en API Connect", readonly=True, copy=False, index=True)
    device_id = fields.Char(string="Device ID (Hikvision)", copy=False)
    device_key = fields.Char(
        string="Device Key (Hikvision)",
        copy=False,
        groups="api_connect.group_apiconnect_manager",
    )
    auto_renew = fields.Boolean(string="Auto-renovación", readonly=True)
    expire_day = fields.Date(string="Vence", readonly=True)
    last_sync = fields.Datetime(string="Última conexión", readonly=True)
    device_type = fields.Char(string="Tipo de equipo", readonly=True)
    device_name = fields.Char(string="Nombre interno del equipo", readonly=True)
    door_count = fields.Integer(string="Puertas (lock count)", readonly=True)
    reader_count = fields.Integer(string="Lectores", readonly=True)
    parameters_json = fields.Text(string="Parámetros del dispositivo", readonly=True)
    params_synced_at = fields.Datetime(string="Parámetros al", readonly=True)
    door_ids = fields.One2many(
        "api.connect.terminal.door", "terminal_id", string="Puertas"
    )
    command_ids = fields.One2many(
        "api.connect.command.log", "terminal_id", string="Comandos"
    )
    online = fields.Boolean(
        string="En línea",
        compute="_compute_online",
        search="_search_online",
    )

    _sql_constraints = [
        ("sn_uniq", "unique(sn)", "El número de serie ya está registrado en Odoo"),
    ]

    @api.model
    def _search_online(self, operator, value):
        if operator not in ("=", "!="):
            operator = "="
        want_online = (operator == "=") == bool(value)
        limit = fields.Datetime.now() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
        if want_online:
            return [("last_sync", ">=", limit)]
        return [
            "|",
            ("last_sync", "<", limit),
            ("last_sync", "=", False),
        ]

    @api.depends("last_sync")
    def _compute_online(self):
        limit = fields.Datetime.now() - timedelta(minutes=ONLINE_WINDOW_MINUTES)
        for terminal in self:
            terminal.online = bool(terminal.last_sync and terminal.last_sync > limit)

    def _sync_vals(self, item):
        api_group = item.get("terminal_group_id")
        group_record = False
        if api_group:
            group_record = self.env["api.connect.terminal.group"].search(
                [("api_id", "=", str(api_group))], limit=1
            )
        return {
            "name": item.get("name") or item.get("sn"),
            "sn": item.get("sn"),
            "model": item.get("model"),
            "brand": (item.get("brand") or "ZK").upper(),
            "tz": item.get("tz"),
            "api_group_id": str(api_group) if api_group else False,
            "group_id": group_record.id if group_record else False,
            "api_id": str(item.get("id") or ""),
            "device_id": item.get("device_id") or None,
            "auto_renew": bool(item.get("auto_renew")),
            "expire_day": _parse_date(item.get("expire_day")),
        }

    @api.model
    def action_sync_from_api(self):
        client = self.env["api.connect.config"].get_client()
        self.env["api.connect.config"].get_singleton().sync_groups_api()
        terminals = client.list_terminals()
        for item in terminals:
            if not item.get("sn"):
                continue
            existing = self.search([("sn", "=", item["sn"])], limit=1)
            if existing:
                existing.write(self._sync_vals(item))
            else:
                self.create(self._sync_vals(item))
        return self.env["api.connect.config"]._notify(
            _("Sincronización completada: %s terminales") % len(terminals)
        )

    def action_create_in_api(self):
        client = self.env["api.connect.config"].get_client()
        for terminal in self:
            if terminal.api_id:
                raise UserError(
                    _("La terminal %s ya existe en API Connect") % terminal.sn
                )
            if not terminal.model:
                raise UserError(
                    _("Indica el modelo de la terminal %s") % terminal.sn
                )
            vals = {
                "sn": terminal.sn,
                "name": terminal.name,
                "model": terminal.model,
                "brand": terminal.brand or "ZK",
                "tz": terminal.tz or None,
            }
            if (terminal.brand or "ZK") == "HK":
                if not terminal.device_id or not terminal.device_key:
                    raise UserError(
                        _(
                            "Las terminales Hikvision requieren Device ID y Device Key "
                            "(%s)"
                        )
                        % terminal.sn
                    )
                vals["device_id"] = terminal.device_id
                vals["device_key"] = terminal.device_key
            try:
                data = client.create_terminal(vals)
            except UserError as exc:
                if "already registered" in str(exc):
                    self.action_sync_from_api()
                    return self.env["api.connect.config"]._notify(
                        _("La terminal ya estaba registrada; lista sincronizada."),
                        "warning",
                    )
                raise
            terminal.write({
                "api_id": str(data.get("id") or ""),
                "name": data.get("name") or terminal.name,
                "model": data.get("model") or terminal.model,
                "brand": (data.get("brand") or terminal.brand or "ZK").upper(),
                "tz": data.get("tz") or terminal.tz,
                "device_id": data.get("device_id") or terminal.device_id,
                "auto_renew": bool(data.get("auto_renew")),
                "expire_day": _parse_date(data.get("expire_day")) or terminal.expire_day,
            })
        return self.env["api.connect.config"]._notify(_("Terminales creadas en API Connect"))

    @api.model
    def _cron_heartbeat(self):
        try:
            client = self.env["api.connect.config"].get_client()
        except UserError:
            _logger.info("API Connect: heartbeat omitido, sin configuración")
            return
        for terminal in self.search([]):
            try:
                message = client.last_sync(terminal.sn)
            except UserError as exc:
                _logger.warning("API Connect heartbeat %s: %s", terminal.sn, exc)
                continue
            if not message:
                continue
            try:
                local_dt = dateutil_parser.isoparse(message)
            except (ValueError, TypeError):
                continue
            if local_dt.tzinfo is None:
                try:
                    local_dt = pytz.timezone(terminal.tz or "UTC").localize(local_dt)
                except Exception:
                    local_dt = pytz.utc.localize(local_dt)
            utc_naive = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
            terminal.write({"last_sync": utc_naive})

    def _log_command(self, action_label, client, status, response):
        self.ensure_one()
        self.env["api.connect.command.log"].sudo().create({
            "terminal_id": self.id,
            "sn": self.sn,
            "action": action_label,
            "status": status,
            "api_response": (response or "")[:4000],
        })

    def _call_api_logged(self, action_label, api_call):
        self.ensure_one()
        client = self.env["api.connect.config"].get_client()
        try:
            data = api_call(client)
            self._log_command(action_label, client, "ok", json.dumps(
                data, ensure_ascii=False, default=str
            )[:4000])
            return data
        except UserError as exc:
            self._log_command(action_label, client, "failed", str(exc))
            raise

    def action_refresh_parameters(self):
        client = self.env["api.connect.config"].get_client()
        for terminal in self:
            if not terminal.api_id:
                raise UserError(
                    _("Registre o sincronice la terminal %s primero") % terminal.sn
                )
            params = client.terminal_parameters(terminal.api_id)
            terminal._apply_parameters(params)
            terminal._log_command(_("Consultar parámetros"), client, "ok", json.dumps(
                params, ensure_ascii=False, default=str
            )[:4000])
        return self.env["api.connect.config"]._notify(_("Parámetros actualizados"))

    def _apply_parameters(self, params):
        self.ensure_one()
        def _int(key):
            try:
                return int(params.get(key) or 0)
            except (TypeError, ValueError):
                return 0
        lock_count = _int("LockCount")
        self.write({
            "device_type": params.get("DeviceType") or "",
            "device_name": params.get("~DeviceName") or "",
            "door_count": lock_count,
            "reader_count": _int("ReaderCount"),
            "parameters_json": json.dumps(params, indent=1, ensure_ascii=False)[:16000],
            "params_synced_at": fields.Datetime.now(),
        })
        Door = self.env["api.connect.terminal.door"].sudo()
        for number in range(1, lock_count + 1):
            if not Door.search_count([
                ("terminal_id", "=", self.id),
                ("door_number", "=", number),
            ]):
                Door.create({
                    "terminal_id": self.id,
                    "door_number": number,
                    "name": _("Puerta %s") % number,
                })

    def action_update_in_api(self):
        for terminal in self:
            if not terminal.api_id:
                raise UserError(
                    _("Registre o sincronice la terminal %s primero") % terminal.sn
                )
            terminal._call_api_logged(_("Actualizar terminal"), lambda c, t=terminal: c.update_terminal(
                t.api_id,
                {
                    "name": t.name,
                    "model": t.model,
                    "tz": t.tz or None,
                },
            ))
        return self.env["api.connect.config"]._notify(_("Terminal actualizada en API Connect"))

    def _run_command(self, cmd, label):
        for terminal in self:
            terminal._call_api_logged(label, lambda c, t=terminal: c.send_command(t.sn, cmd))
        return self.env["api.connect.config"]._notify(_("%s enviado a %s terminal(es)") % (label, len(self)))

    def action_cmd_reboot(self):
        return self._run_command(1, _("Reiniciar terminal"))

    def action_cmd_clear_log(self):
        return self._run_command(2, _("Borrar logs"))

    def action_cmd_clear_data(self):
        return self._run_command(3, _("Borrar datos"))

    def action_cmd_sync_time(self):
        return self._run_command(4, _("Sincronizar hora"))

    def action_cmd_unlock(self):
        return self._run_command(5, _("Abrir puertas (AC_UNLOCK)"))

    def action_cmd_reload_options(self):
        return self._run_command(6, _("Reload options"))

    def action_cmd_check(self):
        return self._run_command(7, _("Check"))

    def action_unlock_quick(self):
        for terminal in self:
            terminal._call_api_logged(_("Desbloqueo rápido"), lambda c, t=terminal: c.unlock(t.sn, 5))
        return self.env["api.connect.config"]._notify(_("Desbloqueo enviado (5 s)"))

    def action_restore_factory(self):
        for terminal in self:
            terminal._call_api_logged(_("Restaurar fábrica"), lambda c, t=terminal: c.restore_factory(t.sn))
        return self.env["api.connect.config"]._notify(_("Restauración enviada"), "warning")

    def action_hk_reset_access(self):
        for terminal in self:
            terminal._call_api_logged(_("Reset de acceso (HK)"), lambda c, t=terminal: c.hk_reset_access(t.sn))
        return self.env["api.connect.config"]._notify(_("Reset de acceso enviado"), "warning")

    def action_hk_factory_settings(self):
        for terminal in self:
            terminal._call_api_logged(_("Fábrica de puertas (HK)"), lambda c, t=terminal: c.hk_factory_settings(t.sn))
        return self.env["api.connect.config"]._notify(_("Comando enviado"), "warning")

    def action_fetch_responses(self):
        from datetime import datetime as dt
        today = dt.utcnow().strftime("%Y-%m-%d")
        for terminal in self:
            terminal._call_api_logged(
                _("Consultar respuestas (%s)") % today,
                lambda c, t=terminal: c.response_logs(t.sn, today),
            )
        return self.env["api.connect.config"]._notify(_("Respuestas consultadas (revisa el log de comandos)"))
