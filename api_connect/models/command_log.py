from odoo import fields, models


class ApiConnectCommandLog(models.Model):
    _name = "api.connect.command.log"
    _description = "API Connect - Comando enviado a terminal"
    _order = "sent_at desc, id desc"

    terminal_id = fields.Many2one(
        "api.connect.terminal", string="Terminal", required=True, ondelete="cascade", index=True
    )
    sn = fields.Char(string="Serial", readonly=True)
    action = fields.Char(string="Acción", readonly=True)
    status = fields.Selection(
        [("ok", "OK"), ("failed", "Fallido")],
        string="Resultado",
        readonly=True,
        index=True,
    )
    api_response = fields.Text(string="Respuesta del dispositivo", readonly=True)
    sent_at = fields.Datetime(string="Enviado", default=fields.Datetime.now, readonly=True)
