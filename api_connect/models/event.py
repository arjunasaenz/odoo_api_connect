import json
import logging
from datetime import datetime, timedelta
from zlib import crc32

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


def _fmt_local(dt_utc_naive, tz_name):
    tz = pytz.timezone(tz_name or "UTC")
    return (
        dt_utc_naive.replace(tzinfo=pytz.utc).astimezone(tz).strftime("%d/%m %H:%M:%S")
    )


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
            ("no_employee", "Sin empleado con ese PIN"),
            ("no_terminal", "Terminal desconocida"),
            ("out_group", "Terminal de otro grupo"),
            ("unmatched", "Sin vincular (histórico)"),
            ("stale", "Fuera de secuencia"),
            ("loose_out", "Salida suelta"),
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

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [crc32(("pin:%s" % pin).encode())],
        )

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
            if not terminal:
                note = "La terminal con serie '%s' no está registrada en Odoo. Sincrónicela y use Reprocesar." % sn
                if not employee:
                    note += " Además, no existe ningún empleado con el PIN '%s'." % pin
                event.write({"state": "no_terminal", "note": note})
            else:
                event.write({
                    "state": "no_employee",
                    "note": "No existe ningún empleado con el PIN '%s'. "
                            "Asigne apiconnect_pin y use Reprocesar." % pin,
                })
            return {"status": 200, "result": "unlinked"}

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
                attendance, failure = event._apply_attendance(
                    employee, timestamp_local, direction, terminal
                )
                if attendance:
                    event.write({
                        "state": "processed",
                        "employee_id": employee.id,
                        "attendance_id": attendance.id,
                        "note": False,
                    })
                else:
                    code, ctx = failure
                    if code == "in_session":
                        att = self.env["hr.attendance"].browse(ctx)
                        event.write({
                            "state": "repeated",
                            "employee_id": employee.id,
                            "note": "La marcación de las %s cae dentro del turno %s - %s: doble marcación."
                                    % (_fmt_local(timestamp_local, terminal.tz),
                                       _fmt_local(att.check_in, terminal.tz),
                                       _fmt_local(att.check_out, terminal.tz)),
                        })
                    else:
                        event.write({
                            "state": code,
                            "employee_id": employee.id,
                            "note": event._discard_note(code, ctx, terminal.tz, timestamp_local),
                        })
            return {"status": 200, "result": "ok" if attendance else "discarded"}
        except ValidationError as exc:
            event.write({"state": "invalid", "note": str(exc), "employee_id": employee.id})
            return {"status": 200, "result": "invalid"}
        except Exception:
            _logger.exception("API Connect webhook: error procesando evento %s", event_id)
            event.write({"state": "error", "note": "excepción al crear marcación", "employee_id": employee.id})
            return {"status": 500, "error": "error interno"}

    def _same_scope(self, terminal, open_record):
        config = self.env["api.connect.config"].sudo().get_singleton()
        if config.pairing_global:
            return True
        if not open_record.apiconnect_terminal_in_id:
            return True
        if not terminal:
            return False
        return open_record.apiconnect_terminal_in_id.group_id == terminal.group_id

    def _apply_attendance(self, employee, ts_utc, direction, terminal=None):
        Attendance = self.env["hr.attendance"]
        containing = Attendance.search([
            ("employee_id", "=", employee.id),
            ("check_in", "<", ts_utc),
            ("check_out", ">", ts_utc),
        ], limit=1)
        if containing:
            return None, ("in_session", containing.id)
        open_record = Attendance.search(
            [("employee_id", "=", employee.id), ("check_out", "=", False)],
            limit=1,
        )
        if open_record:
            same_scope = self._same_scope(terminal, open_record)
            if ts_utc > open_record.check_in:
                if not same_scope:
                    return None, ("out_group", open_record.apiconnect_terminal_in_id)
                open_record.write({"check_out": ts_utc})
            else:
                return None, ("stale", open_record.check_in)
        if direction == "out":
            if open_record:
                return open_record, None
            return None, ("loose_out", None)
        if direction in ("in", "auto"):
            if open_record and ts_utc <= open_record.check_in:
                if not self._same_scope(terminal, open_record):
                    return None, ("out_group", open_record.apiconnect_terminal_in_id)
                return None, ("stale", open_record.check_in)
            vals = {"employee_id": employee.id, "check_in": ts_utc}
            if terminal:
                vals["apiconnect_terminal_in_id"] = terminal.id
            return Attendance.create(vals), None
        return None, ("stale", None)

    def _discard_note(self, code, ctx, tz_name, punch_ts):
        if code == "stale":
            open_check_in = ctx
            if open_check_in:
                return (
                    "La marcación de las %s es ANTERIOR al inicio del turno abierto "
                    "(%s). La marcación se descartó para no corromper la asistencia; "
                    "revise el reloj del terminal."
                    % (_fmt_local(punch_ts, tz_name), _fmt_local(open_check_in, tz_name))
                )
            return "Dirección no reconocida en la marcación de las %s." % _fmt_local(
                punch_ts, tz_name
            )
        if code == "out_group":
            open_terminal = ctx
            if open_terminal:
                return (
                    "La marcación llegó desde una terminal de OTRO grupo; el turno "
                    "abierto corresponde a la terminal '%s' y solo puede cerrarse "
                    "desde su mismo grupo. La marcación se ignoró." % open_terminal.name
                )
            return "La marcación llegó desde una terminal de otro grupo y se ignoró."
        if code == "loose_out":
            return "Salida recibida sin un turno abierto a quién cerrar."
        return "Marcación descartada."

    def _attendance_between(self, employee, start_ts, end_ts):
        return bool(
            self.env["hr.attendance"].search_count([
                ("employee_id", "=", employee.id),
                ("check_in", ">", start_ts),
                ("check_in", "<", end_ts),
            ])
        )

    def action_reprocess(self):
        events = self.filtered(
            lambda e: e.state in ("unmatched", "no_employee", "stale")
        )
        window = self._punch_window_minutes()
        processed = 0
        repeated = 0
        no_employee = 0
        discarded = 0

        by_pin = {}
        for ev in events:
            by_pin.setdefault(ev.pin, []).append(ev)

        for pin, evs in by_pin.items():
            employee = self.env["hr.employee"].search(
                [("apiconnect_pin", "=", pin)], limit=1
            )
            if not employee:
                for ev in evs:
                    ev.write({
                        "state": "no_employee",
                        "note": "No existe ningún empleado con el PIN '%s'. "
                                "Asigne apiconnect_pin y use Reprocesar." % pin,
                    })
                no_employee += len(evs)
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
            tzs = evs[0].terminal_id.tz if evs and evs[0].terminal_id else None

            sessions = []
            cur_in_ts = None
            cur_in_event = None
            pin_proc = 0
            pin_rep = 0
            pin_disc = 0
            deferred = []

            for ev in evs:
                ts = ev.timestamp_local
                if ts is None:
                    pin_disc += 1
                    continue
                containing = Attendance.search([
                    ("employee_id", "=", employee.id),
                    ("check_in", "<", ts),
                    ("check_out", ">", ts),
                ], limit=1)
                if containing:
                    deferred.append((ev, "repeated", "La marcación de las %s cae dentro del turno %s - %s: doble marcación."
                                     % (_fmt_local(ts, tzs),
                                        _fmt_local(containing.check_in, tzs),
                                        _fmt_local(containing.check_out, tzs))))
                    pin_rep += 1
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
                    deferred.append((ev, "loose_out", "Salida recibida sin un turno abierto a quien cerrar."))
                    pin_disc += 1
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
                    deferred.append((cur_in_event, "stale", "La marcacion de las %s llega despues del inicio del turno abierto (%s) y ya existe otra sesion en ese intervalo; no se puede emparejar." % (_fmt_local(cur_in_ts, tzs), _fmt_local(live_open.check_in, tzs))))
                    pin_disc += 1

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
                        else:
                            ev.write({"state": action, "employee_id": employee.id, "note": note})
                processed += pin_proc
                repeated += pin_rep
                discarded += pin_disc
            except ValidationError as exc:
                for ev in evs:
                    ev.write({"state": "invalid", "employee_id": employee.id, "note": str(exc)})
                discarded += len(evs)

        return self.env["api.connect.config"]._notify(
            "Reprocesadas: %s · Repetidas: %s · Sin empleado: %s · Descartadas: %s"
            % (processed, repeated, no_employee, discarded)
        )
