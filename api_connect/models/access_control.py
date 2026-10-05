import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DAYS = [
    ("sun", "Domingo"),
    ("mon", "Lunes"),
    ("tue", "Martes"),
    ("wed", "Miércoles"),
    ("thu", "Jueves"),
    ("fri", "Viernes"),
    ("sat", "Sábado"),
]

DAYS_BY_CODE = dict(DAYS)


def _hhmm(value):
    return (value or "").replace(":", "") or "0000"


class ApiConnectAccessSchedule(models.Model):
    _name = "api.connect.access.schedule"
    _description = "API Connect - Horario de acceso"
    _order = "terminal_id, schedule_number"

    terminal_id = fields.Many2one(
        "api.connect.terminal", string="Terminal", required=True, ondelete="cascade"
    )
    schedule_number = fields.Integer(
        string="Número de horario",
        required=True,
        help="ZKTeco: access_time_id (1-50). Hikvision: access_schedule_number (1-64).",
    )
    synced_once = fields.Boolean(default=False, readonly=True, copy=False)
    synced_at = fields.Datetime(readonly=True, copy=False)

    sun_start1 = fields.Char(string="Domingo inicio P1", help="HH:MM")
    sun_end1 = fields.Char(string="Domingo fin P1")
    sun_start2 = fields.Char(string="Domingo inicio P2")
    sun_end2 = fields.Char(string="Domingo fin P2")
    sun_start3 = fields.Char(string="Domingo inicio P3")
    sun_end3 = fields.Char(string="Domingo fin P3")
    mon_start1 = fields.Char(string="Lunes inicio P1")
    mon_end1 = fields.Char(string="Lunes fin P1")
    mon_start2 = fields.Char(string="Lunes inicio P2")
    mon_end2 = fields.Char(string="Lunes fin P2")
    mon_start3 = fields.Char(string="Lunes inicio P3")
    mon_end3 = fields.Char(string="Lunes fin P3")
    tue_start1 = fields.Char(string="Martes inicio P1")
    tue_end1 = fields.Char(string="Martes fin P1")
    tue_start2 = fields.Char(string="Martes inicio P2")
    tue_end2 = fields.Char(string="Martes fin P2")
    tue_start3 = fields.Char(string="Martes inicio P3")
    tue_end3 = fields.Char(string="Martes fin P3")
    wed_start1 = fields.Char(string="Miércoles inicio P1")
    wed_end1 = fields.Char(string="Miércoles fin P1")
    wed_start2 = fields.Char(string="Miércoles inicio P2")
    wed_end2 = fields.Char(string="Miércoles fin P2")
    wed_start3 = fields.Char(string="Miércoles inicio P3")
    wed_end3 = fields.Char(string="Miércoles fin P3")
    thu_start1 = fields.Char(string="Jueves inicio P1")
    thu_end1 = fields.Char(string="Jueves fin P1")
    thu_start2 = fields.Char(string="Jueves inicio P2")
    thu_end2 = fields.Char(string="Jueves fin P2")
    thu_start3 = fields.Char(string="Jueves inicio P3")
    thu_end3 = fields.Char(string="Jueves fin P3")
    fri_start1 = fields.Char(string="Viernes inicio P1")
    fri_end1 = fields.Char(string="Viernes fin P1")
    fri_start2 = fields.Char(string="Viernes inicio P2")
    fri_end2 = fields.Char(string="Viernes fin P2")
    fri_start3 = fields.Char(string="Viernes inicio P3")
    fri_end3 = fields.Char(string="Viernes fin P3")
    sat_start1 = fields.Char(string="Sábado inicio P1")
    sat_end1 = fields.Char(string="Sábado fin P1")
    sat_start2 = fields.Char(string="Sábado inicio P2")
    sat_end2 = fields.Char(string="Sábado fin P2")
    sat_start3 = fields.Char(string="Sábado inicio P3")
    sat_end3 = fields.Char(string="Sábado fin P3")

    _sql_constraints = [
        (
            "schedule_uniq",
            "unique(terminal_id, schedule_number)",
            "Ya existe un horario con ese número en la terminal",
        ),
    ]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "api.connect.terminal":
            terminal = self.env["api.connect.terminal"].browse(
                self.env.context.get("active_id")
            )
            if terminal.exists():
                res["terminal_id"] = terminal.id
        return res

    def _payload(self, brand):
        self.ensure_one()
        if brand == "HK":
            payload = {"access_schedule_number": self.schedule_number}
            for day_code, _label in DAYS:
                for period in (1, 2, 3):
                    start = getattr(self, "%s_start%s" % (day_code, period))
                    end = getattr(self, "%s_end%s" % (day_code, period))
                    payload["%s_start_%s" % (day_code, period)] = _hhmm(start)
                    payload["%s_end_%s" % (day_code, period)] = _hhmm(end)
            return payload
        payload = {"access_time_id": self.schedule_number}
        for day_code, _label in DAYS:
            for period in (1, 2, 3):
                start = getattr(self, "%s_start%s" % (day_code, period))
                end = getattr(self, "%s_end%s" % (day_code, period))
                if period == 1:
                    payload["%s_start" % day_code] = start or "00:00"
                    payload["%s_end" % day_code] = end or "00:00"
                elif start or end:
                    payload["%s_start_%s" % (day_code, period)] = start or "00:00"
                    payload["%s_end_%s" % (day_code, period)] = end or "00:00"
        return payload

    def action_set_schedule(self):
        client = self.env["api.connect.config"].get_client()
        for schedule in self:
            terminal = schedule.terminal_id
            if not terminal.api_id:
                raise UserError(
                    _("Registre o sincronice la terminal %s primero") % terminal.sn
                )
            payload = schedule._payload(terminal.brand)
            if terminal.brand == "HK":
                method = "hk_set_access_time"
                update = schedule.synced_once
                schedule._send_schedule_call(
                    client, method, payload, update,
                    _("Horario %s (HK)") % schedule.schedule_number,
                )
            else:
                schedule._send_schedule_call(
                    client, "zk_set_access_time", payload, False,
                    _("Horario %s (ZK)") % schedule.schedule_number,
                )
            schedule.write({"synced_once": True, "synced_at": fields.Datetime.now()})
        return self.env["api.connect.config"]._notify(_("Horarios enviados al dispositivo"))

    def _send_schedule_call(self, client, method, payload, update, label):
        self.ensure_one()
        terminal = self.terminal_id
        terminal._call_api_logged(
            label,
            lambda c: getattr(c, method)(terminal.sn, payload, update=update),
        )

    def action_delete_schedule(self):
        client = self.env["api.connect.config"].get_client()
        for schedule in self:
            terminal = schedule.terminal_id
            if terminal.brand == "HK":
                raise UserError(
                    _("La API no expone borrado de horarios para Hikvision")
                )
            terminal._call_api_logged(
                _("Borrar horario %s") % schedule.schedule_number,
                lambda c: c.zk_delete_access_time(
                    terminal.sn, schedule.schedule_number
                ),
            )
            schedule.unlink()
        return self.env["api.connect.config"]._notify(_("Horarios borrados"), "warning")


class ApiConnectAccessHoliday(models.Model):
    _name = "api.connect.access.holiday"
    _description = "API Connect - Feriado de acceso"
    _order = "terminal_id, holiday_number"

    terminal_id = fields.Many2one(
        "api.connect.terminal", string="Terminal", required=True, ondelete="cascade"
    )
    holiday_number = fields.Integer(
        string="Número (ZK)",
        help="access_holiday_id de ZKTeco (1 en adelante)",
    )
    name = fields.Char(string="Nombre (ZK)")
    start_date = fields.Char(
        string="Fecha inicio (MM-DD)", required=True, help="Formato MM-DD"
    )
    end_date = fields.Char(string="Fecha fin (MM-DD)")
    year = fields.Integer(string="Año (vacío = anual)")
    holiday_type = fields.Integer(
        string="Tipo",
        default=1,
        help="1-3 (ZK). Hikvision lo usa como tipo de recurrencia",
    )
    holiday_loop = fields.Integer(string="Loop (HK)")
    access_time_id = fields.Integer(string="Horario asociado (ZK asistencia)")
    synced_once = fields.Boolean(default=False, readonly=True, copy=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "api.connect.terminal":
            terminal = self.env["api.connect.terminal"].browse(
                self.env.context.get("active_id")
            )
            if terminal.exists():
                res["terminal_id"] = terminal.id
        return res

    def action_set_holiday(self):
        client = self.env["api.connect.config"].get_client()
        for holiday in self:
            terminal = holiday.terminal_id
            if not terminal.api_id:
                raise UserError(
                    _("Registre o sincronice la terminal %s primero") % terminal.sn
                )
            if terminal.brand == "HK":
                payload = {
                    "holiday_access_date": holiday.start_date,
                    "holiday_type": holiday.holiday_type or 1,
                    "holiday_loop": holiday.holiday_loop or 0,
                }
                method = "hk_set_holiday"
                update = holiday.synced_once
            else:
                if not holiday.holiday_number or not holiday.name:
                    raise UserError(
                        _("ZKTeco requiere número de feriado y nombre: %s") % holiday.start_date
                    )
                payload = {
                    "access_holiday_id": holiday.holiday_number,
                    "name": holiday.name,
                    "start_date": holiday.start_date,
                }
                if holiday.end_date:
                    payload["end_date"] = holiday.end_date
                if holiday.year:
                    payload["year"] = holiday.year
                if holiday.holiday_type:
                    payload["holiday_type"] = holiday.holiday_type
                if holiday.access_time_id:
                    payload["access_time_id"] = holiday.access_time_id
                method = "zk_set_holiday"
                update = False
            terminal._call_api_logged(
                _("Feriado %s") % (holiday.name or holiday.start_date),
                lambda c: getattr(c, method)(terminal.sn, payload, update=update),
            )
            holiday.write({"synced_once": True})
        return self.env["api.connect.config"]._notify(_("Feriados enviados al dispositivo"))
