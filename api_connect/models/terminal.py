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
        return {
            "name": item.get("name") or item.get("sn"),
            "sn": item.get("sn"),
            "model": item.get("model"),
            "brand": (item.get("brand") or "ZK").upper(),
            "tz": item.get("tz"),
            "api_id": str(item.get("id") or ""),
            "device_id": item.get("device_id") or None,
            "auto_renew": bool(item.get("auto_renew")),
            "expire_day": _parse_date(item.get("expire_day")),
        }

    @api.model
    def action_sync_from_api(self):
        client = self.env["api.connect.config"].get_client()
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
