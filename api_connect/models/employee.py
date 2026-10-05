import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

BULK_CHUNK = 300


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    apiconnect_terminal_in_id = fields.Many2one(
        "api.connect.terminal",
        string="Terminal de entrada",
        readonly=True,
        ondelete="set null",
        help="Terminal desde la que se marc? la entrada (grupo propietario del ciclo)",
    )


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    apiconnect_pin = fields.Char(
        string="PIN API Connect",
        copy=False,
        index=True,
        help="PIN único del empleado en los terminales de API Connect",
    )
    apiconnect_expiration = fields.Date(
        string="Expira en terminales",
        copy=False,
        help="Fecha de expiración del acceso en los terminales (vacío = sin vencimiento)",
    )
    apiconnect_terminal_ids = fields.Many2many(
        "api.connect.terminal",
        relation="apiconnect_employee_terminal_rel",
        string="Terminales API Connect",
    )

    _sql_constraints = [
        (
            "apiconnect_pin_uniq",
            "unique(apiconnect_pin)",
            "El PIN de API Connect ya est? asignado a otro empleado",
        ),
    ]

    def _apiconnect_client(self):
        return self.env["api.connect.config"].get_client()

    def _apiconnect_ensure_pin(self):
        missing = self.filtered(lambda e: not e.apiconnect_pin)
        if missing:
            raise UserError(
                _("Asigna un PIN de API Connect a: %s")
                % ", ".join(missing.mapped("name"))
            )

    def _apiconnect_payload(self):
        self.ensure_one()
        payload = {
            "pin": self.apiconnect_pin,
            "full_name": self.name,
            "privilege": 0,
            "access_group_number": 1,
        }
        if self.barcode:
            payload["card_number"] = self.barcode
        if self.apiconnect_expiration:
            payload["expiration_date"] = self.apiconnect_expiration.isoformat()
        return payload

    def _apiconnect_photo_url(self):
        self.ensure_one()
        config = self.env["api.connect.config"].sudo().get_singleton()
        return "%s/api_connect/employee_photo/%s/%s" % (
            self.env["api.connect.config"]._webhook_base_url(),
            config.webhook_secret,
            self.id,
        )

    def _apiconnect_run(self, label, action):
        client = self._apiconnect_client()
        failures = []
        for employee in self:
            for terminal in employee.apiconnect_terminal_ids:
                try:
                    action(client, employee, terminal)
                except UserError as exc:
                    failures.append("%s ? %s: %s" % (employee.name, terminal.sn, exc))
        if failures:
            raise UserError(
                _("%s completado con errores:\n%s") % (label, "\n".join(failures))
            )
        return self.env["api.connect.config"]._notify(
            _("%s completado sin errores") % label
        )

    def action_register_in_terminals(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            client.create_customer(terminal.sn, employee._apiconnect_payload())

        return self._apiconnect_run(_("Registro de empleados"), action)

    def action_update_in_terminals(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            client.update_customer(terminal.sn, employee._apiconnect_payload())

        return self._apiconnect_run(_("Actualización de empleados"), action)

    def action_renew_expiration(self):
        self._apiconnect_ensure_pin()
        missing = self.filtered(lambda e: not e.apiconnect_expiration)
        if missing:
            raise UserError(
                _("Define la fecha 'Expira en terminales' en: %s")
                % ", ".join(missing.mapped("name"))
            )

        def action(client, employee, terminal):
            client.renew_expiration(
                terminal.sn,
                employee.apiconnect_pin,
                employee.apiconnect_expiration.isoformat(),
            )

        return self._apiconnect_run(_("Renovación de expiración"), action)

    def action_register_card(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            if not employee.barcode:
                raise UserError(
                    _("El empleado %s no tiene número de tarjeta (badge)") % employee.name
                )
            client.add_card(terminal.sn, employee.apiconnect_pin, employee.barcode)

        return self._apiconnect_run(_("Registro de tarjetas"), action)

    def action_delete_card(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            client.delete_card(terminal.sn, employee.apiconnect_pin)

        return self._apiconnect_run(_("Borrado de tarjetas"), action)

    def action_register_face(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            if not employee.image_1920:
                raise UserError(
                    _("El empleado %s no tiene foto en su ficha") % employee.name
                )
            client.add_biophoto(
                terminal.sn,
                employee.apiconnect_pin,
                employee._apiconnect_photo_url(),
            )

        return self._apiconnect_run(_("Registro de rostros"), action)

    def action_delete_biophoto(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            client.delete_biophoto(terminal.sn, employee.apiconnect_pin)

        return self._apiconnect_run(_("Borrado de rostros"), action)

    def action_register_photo(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            if not employee.image_1920:
                raise UserError(
                    _("El empleado %s no tiene foto en su ficha") % employee.name
                )
            client.add_photo(
                terminal.sn,
                employee.apiconnect_pin,
                employee.image_1920,
            )

        return self._apiconnect_run(_("Registro de fotos en pantalla"), action)

    def action_invite_selfie(self):
        self.ensure_one()
        self._apiconnect_ensure_pin()
        if not self.work_email:
            raise UserError(
                _("El empleado %s necesita email de trabajo") % self.name
            )
        sns = self.apiconnect_terminal_ids.mapped("sn")
        if not sns:
            raise UserError(
                _("El empleado %s no tiene terminales asignadas") % self.name
            )
        client = self._apiconnect_client()
        client.invite_selfie(
            sns, self.work_email, self.apiconnect_pin, self.name
        )
        return self.env["api.connect.config"]._notify(
            _("Invitación selfie enviada a %s") % self.work_email
        )

    def action_register_fingerprint(self):
        self.ensure_one()
        self._apiconnect_ensure_pin()
        return {
            "type": "ir.actions.act_window",
            "res_model": "api.connect.fingerprint.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_employee_id": self.id},
        }

    def action_register_biodata(self):
        self.ensure_one()
        self._apiconnect_ensure_pin()
        return {
            "type": "ir.actions.act_window",
            "res_model": "api.connect.biodata.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_employee_id": self.id},
        }

    def action_set_access_group(self):
        self.ensure_one()
        self._apiconnect_ensure_pin()
        return {
            "type": "ir.actions.act_window",
            "res_model": "api.connect.employee.accessgroup.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_employee_ids": [(6, 0, self.ids)]},
        }

    def action_remove_from_terminals(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            client.delete_customer(terminal.sn, employee.apiconnect_pin)

        return self._apiconnect_run(_("Baja de empleados"), action)

    def action_bulk_register(self):
        self._apiconnect_ensure_pin()
        client = self._apiconnect_client()
        by_terminal = {}
        for employee in self:
            payload = employee._apiconnect_payload()
            for terminal in employee.apiconnect_terminal_ids:
                by_terminal.setdefault(terminal, []).append(payload)
        if not by_terminal:
            raise UserError(
                _("Los empleados seleccionados no tienen terminales asignadas")
            )
        summaries = []
        for terminal, customers in by_terminal.items():
            for i in range(0, len(customers), BULK_CHUNK):
                chunk = customers[i:i + BULK_CHUNK]
                try:
                    result = client.bulk_create_customers(terminal.sn, chunk)
                    summaries.append("%s: %s" % (terminal.sn, result.get("message", "")))
                except UserError as exc:
                    summaries.append("%s: %s" % (terminal.sn, exc))
        return self.env["api.connect.config"]._notify(
            _("Alta masiva: %s") % " | ".join(summaries)
        )

    def action_bulk_remove(self):
        self._apiconnect_ensure_pin()
        client = self._apiconnect_client()
        by_terminal = {}
        for employee in self:
            for terminal in employee.apiconnect_terminal_ids:
                by_terminal.setdefault(terminal, []).append(employee.apiconnect_pin)
        summaries = []
        for terminal, pins in by_terminal.items():
            try:
                result = client.bulk_delete_customers(terminal.sn, pins)
                summaries.append("%s: %s" % (terminal.sn, result.get("message", "")))
            except UserError as exc:
                summaries.append("%s: %s" % (terminal.sn, exc))
        return self.env["api.connect.config"]._notify(
            _("Baja masiva: %s") % " | ".join(summaries)
        )
