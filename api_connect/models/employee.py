import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    apiconnect_pin = fields.Char(
        string="PIN API Connect",
        copy=False,
        index=True,
        help="PIN único del empleado en los terminales de API Connect",
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
            "El PIN de API Connect ya está asignado a otro empleado",
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
                    failures.append("%s → %s: %s" % (employee.name, terminal.sn, exc))
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
            payload = {
                "pin": employee.apiconnect_pin,
                "full_name": employee.name,
                "privilege": 0,
                "access_group_number": 1,
            }
            if employee.badge_id:
                payload["card_number"] = employee.badge_id
            client.create_customer(terminal.sn, payload)

        return self._apiconnect_run(_("Registro de empleados"), action)

    def action_register_card(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            if not employee.badge_id:
                raise UserError(
                    _("El empleado %s no tiene número de tarjeta (badge)") % employee.name
                )
            client.add_card(terminal.sn, employee.apiconnect_pin, employee.badge_id)

        return self._apiconnect_run(_("Registro de tarjetas"), action)

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

    def action_remove_from_terminals(self):
        self._apiconnect_ensure_pin()

        def action(client, employee, terminal):
            client.delete_customer(terminal.sn, employee.apiconnect_pin)

        return self._apiconnect_run(_("Baja de empleados"), action)
