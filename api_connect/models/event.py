import json
import logging
from datetime import datetime, timedelta

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
            ("repeated", "Repetida"),
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
    def _punch_window_minutes(self):
        try:
            return float(
                self.env["api.connect.config"].sudo().get_singleton().punch_window_minutes
                or 0.0
            )
        except Exception:
            return 0.0

    def _is_repeated(self, employee, ts_utc, window_minutes):
        if not window_minutes or window_minutes <= 0:
            return False
        limit = ts_utc - timedelta(minutes=window_minutes)
        return bool(
            self.sudo().search(
                [
                    ("employee_id", "=", employee.id),
                    ("state", "in", ("processed", "repeated")),
                    ("timestamp_local", ">", limit),
                    ("timestamp_local", "<=", ts_utc),
                ],
                limit=1,
            )
        )

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

        window = self._punch_window_minutes()
        if self._is_repeated(employee, timestamp_local, window):
            event.write({
                "state": "repeated",
                "employee_id": employee.id,
                "note": "Repetida dentro de la ventana anti-repetición (%s min)" % window,
            })
            return {"status": 200, "result": "repeated"}

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

    def _attendance_between(self, employee, start_ts, end_ts):
        return bool(
            self.env["hr.attendance"].search_count([
                ("employee_id", "=", employee.id),
                ("check_in", ">", start_ts),
                ("check_in", "<", end_ts),
            ])
        )

    def action_reprocess(self):
        events = self.filtered(lambda e: e.state == "unmatched")
        window = self._punch_window_minutes()
        processed = 0
        repeated = 0
        unmatched = 0

        by_pin = {}
        for ev in events:
            by_pin.setdefault(ev.pin, []).append(ev)

        for pin, evs in by_pin.items():
            employee = self.env["hr.employee"].search(
                [("apiconnect_pin", "=", pin)], limit=1
            )
            if not employee:
                unmatched += len(evs)
                continue

            evs.sort(key=lambda e: e.timestamp_local or e.received_at)
            Attendance = self.env["hr.attendance"]
            live_open = Attendance.search(
                [("employee_id", "=", employee.id), ("check_out", "=", False)],
                limit=1,
            )
            prior = self.sudo().search([
                ("employee_id", "=", employee.id),
                ("state", "in", ("processed", "repeated")),
                ("timestamp_local", "<", evs[0].timestamp_local),
            ], order="timestamp_local desc", limit=1)
            prev_ts = prior.timestamp_local if prior else None

            sessions = []
            cur_in_ts = None
            cur_in_event = None
            pin_proc = 0
            pin_rep = 0
            pin_unm = 0
            deferred = []

            for ev in evs:
                ts = ev.timestamp_local
                if ts is None:
                    pin_unm += 1
                    continue
                if window and prev_ts and (ts - prev_ts) <= timedelta(minutes=window):
                    deferred.append((ev, "repeated", None))
                    pin_rep += 1
                    prev_ts = ts
                    continue
                prev_ts = ts
                if cur_in_ts and ts > cur_in_ts:
                    sessions.append((cur_in_event, cur_in_ts, ev, ts))
                    cur_in_ts = None
                    cur_in_event = None
                    pin_proc += 2
                elif cur_in_ts and ts <= cur_in_ts:
                    deferred.append((ev, "repeated", None))
                    pin_rep += 1
                    continue
                elif ev.direction == "out":
                    deferred.append((ev, "skip", "Salida sin turno abierto"))
                    pin_unm += 1
                else:
                    cur_in_ts = ts
                    cur_in_event = ev

            if cur_in_event:
                if live_open and cur_in_ts < live_open.check_in and not self._attendance_between(
                    employee, cur_in_ts, live_open.check_in
                ):
                    sessions.append(("MERGE", cur_in_event, cur_in_ts))
                    pin_proc += 1
                elif not live_open:
                    sessions.append(("OPEN", cur_in_event, cur_in_ts))
                    pin_proc += 1
                else:
                    deferred.append((cur_in_event, "invalid", "No se puede emparejar con el turno abierto actual"))
                    pin_unm += 1

            try:
                with self.env.cr.savepoint():
                    for item in sessions:
                        if item[0] == "MERGE":
                            _, ev, ts = item
                            live_open.write({"check_in": ts})
                            ev.write({
                                "state": "processed",
                                "employee_id": employee.id,
                                "attendance_id": live_open.id,
                                "note": False,
                            })
                        elif item[0] == "OPEN":
                            _, ev, ts = item
                            att = Attendance.create({"employee_id": employee.id, "check_in": ts})
                            ev.write({
                                "state": "processed",
                                "employee_id": employee.id,
                                "attendance_id": att.id,
                                "note": False,
                            })
                        else:
                            ev_in, in_ts, ev_out, out_ts = item
                            att = Attendance.create({
                                "employee_id": employee.id,
                                "check_in": in_ts,
                                "check_out": out_ts,
                            })
                            ev_in.write({
                                "state": "processed",
                                "employee_id": employee.id,
                                "attendance_id": att.id,
                                "note": False,
                            })
                            ev_out.write({
                                "state": "processed",
                                "employee_id": employee.id,
                                "attendance_id": att.id,
                                "note": False,
                            })
                    for ev, action, note in deferred:
                        if action == "repeated":
                            ev.write({
                                "state": "repeated",
                                "employee_id": employee.id,
                                "note": "Repetida dentro de la ventana anti-repetición (%s min)" % window,
                            })
                        elif action == "invalid":
                            ev.write({"state": "invalid", "employee_id": employee.id, "note": note})
                        else:
                            ev.write({"state": "unmatched", "employee_id": employee.id, "note": note})
                processed += pin_proc
                repeated += pin_rep
                unmatched += pin_unm
            except ValidationError as exc:
                for ev in evs:
                    ev.write({"state": "invalid", "employee_id": employee.id, "note": str(exc)})
                unmatched += len(evs)

        return self.env["api.connect.config"]._notify(
            "Reprocesadas: %s · Repetidas: %s · Sin empleado: %s"
            % (processed, repeated, unmatched)
        )
