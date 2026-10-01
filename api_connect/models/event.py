import json
import logging
from datetime import datetime

import pytz
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

DIRECTION_MAP = {
    "0": "in",
    "3": "in",
    "4": "in",
    "1": "out",
    "2": "out",
    "5": "out",
}

DIRECTION_LABELS = {
    "in": _("Entrada"),
    "out": _("Salida"),
    "auto": _("Automática"),
}


def _parse_timestamp(date_s, time_s, tz_name):
    try:
        naive = datetime.strptime("%s %s" % (date_s, time_s), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None
    try:
        tz = pytz.timezone(tz_name or "UTC")
    except Exception:
        tz = pytz.utc
    try:
        local = tz.localize(naive)
    except Exception:
        local = pytz.utc.localize(naive)
    return local.astimezone(pytz.utc).replace(tzinfo=None)


class ApiConnectEvent(models.Model):
    _name = "api.connect.event"
    _description = "API Connect - Marcación recibida"
    _order = "received_at desc, id desc"

    event_id = fields.Char(string="ID del evento", index=True, copy=False)
    terminal_id = fields.Many2one(
        "api.connect.terminal", string="Terminal", readonly=True, ondelete="set null"
    )
    sn = fields.Char(string="Serial", readonly=True)
    pin = fields.Char(string="PIN", readonly=True)
    event_type = fields.Char(string="Tipo de evento", readonly=True)
    direction = fields.Selection(
        [("in", "Entrada"), ("out", "Salida"), ("auto", "Automática")],
        string="Dirección",
        default="auto",
    )
    timestamp_local = fields.Datetime(string="Hora local", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Empleado", readonly=True, ondelete="set null")
    attendance_id = fields.Many2one(
        "hr.attendance", string="Marcación", readonly=True, ondelete="set null"
    )
    state = fields.Selection(
        [
            ("processed", "Procesada"),
            ("unmatched", "Sin empleado/terminal"),
            ("invalid", "Inválida"),
            ("error", "Error"),
        ],
        string="Estado",
        default="unmatched",
        index=True,
    )
    note = fields.Char(string="Nota", readonly=True)
    payload = fields.Text(string="Payload crudo", readonly=True)
    received_at = fields.Datetime(string="Recibida", default=fields.Datetime.now, readonly=True)

    _sql_constraints = [
        (
            "event_id_uniq",
            "unique(event_id)",
            "Marcación duplicada (mismo ID de evento)",
        ),
    ]

    @api.model
    def process_webhook(self, payload):
        if not isinstance(payload, dict):
            return {"status": 400, "error": "payload inválido"}
        sn = str(payload.get("Serial number") or "").strip()
        pin = str(payload.get("Pin") or "").strip()
        date_s = str(payload.get("Date") or "").strip()
        time_s = str(payload.get("Time") or "").strip()
        event_type = str(payload.get("Event Type") or "Punch")
        event_id = str(payload.get("ID Event") or "").strip()
        in_out = str(payload.get("InOut") or "").strip()

        if not sn or not pin or not date_s or not time_s:
            return {"status": 400, "error": "campos faltantes"}

        direction = DIRECTION_MAP.get(in_out, "auto")

        if not event_id:
            event_id = "auto:%s|%s|%s %s" % (sn, pin, date_s, time_s)

        existing = self.search([("event_id", "=", event_id)], limit=1)
        if existing:
            return {"status": 200, "result": "duplicate"}

        terminal = self.env["api.connect.terminal"].search([("sn", "=", sn)], limit=1)
        timestamp_local = _parse_timestamp(date_s, time_s, terminal.tz)
        if timestamp_local is None:
            return {"status": 400, "error": "fecha/hora inválida"}

        employee = self.env["hr.employee"].search(
            [("apiconnect_pin", "=", pin)], limit=1
        )

        base_vals = {
            "event_id": event_id,
            "terminal_id": terminal.id if terminal else False,
            "sn": sn,
            "pin": pin,
            "event_type": event_type,
            "direction": direction,
            "timestamp_local": timestamp_local,
            "payload": json.dumps(payload, default=str)[:8000],
            "received_at": fields.Datetime.now(),
        }

        try:
            event = self.create(base_vals)
        except Exception:
            existing = self.search([("event_id", "=", event_id)], limit=1)
            if existing:
                return {"status": 200, "result": "duplicate"}
            raise

        if not terminal or not employee:
            event.write({
                "state": "unmatched",
                "note": "" if terminal else "terminal desconocida",
                "employee_id": employee.id if employee else False,
            })
            return {"status": 200, "result": "unmatched"}

        try:
            with self.env.cr.savepoint():
                attendance = event._apply_attendance(employee, timestamp_local, direction)
                if attendance:
                    event.write({
                        "state": "processed",
                        "employee_id": employee.id,
                        "attendance_id": attendance.id,
                    })
                else:
                    event.write({
                        "state": "unmatched",
                        "note": "sin turno abierto para registrar salida",
                        "employee_id": employee.id,
                    })
            return {"status": 200, "result": "ok"}
        except ValidationError as exc:
            event.write({"state": "invalid", "note": str(exc), "employee_id": employee.id})
            return {"status": 200, "result": "invalid"}
        except Exception:
            _logger.exception("API Connect webhook: error procesando evento %s", event_id)
            event.write({"state": "error", "note": "excepción al crear marcación", "employee_id": employee.id})
            return {"status": 500, "error": "error interno"}

    def _apply_attendance(self, employee, ts_utc, direction):
        open_record = self.env["hr.attendance"].search(
            [("employee_id", "=", employee.id), ("check_out", "=", False)],
            limit=1,
        )
        Attendance = self.env["hr.attendance"]
        if open_record:
            if ts_utc > open_record.check_in:
                open_record.write({"check_out": ts_utc})
            else:
                return None
        if direction == "out":
            return open_record if open_record else None
        if direction in ("in", "auto"):
            if open_record and ts_utc <= open_record.check_in:
                return None
            return Attendance.create({"employee_id": employee.id, "check_in": ts_utc})
        return None
