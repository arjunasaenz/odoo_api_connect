import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ApiConnectWebhookRetry(models.Model):
    _name = "api.connect.webhook.retry"
    _description = "API Connect - Webhook fallido (cola de reintentos)"
    _order = "event_time desc, id desc"

    uuid = fields.Char(string="ID del reintento", readonly=True, index=True)
    estado = fields.Selection(
        [
            ("vivo", "Pendiente de entrega"),
            ("muerto", "Descartado (dead-letter)"),
            ("reprocesado", "Reprocesado en Odoo"),
        ],
        string="Estado",
        default="vivo",
        index=True,
    )
    sn = fields.Char(string="Serial", readonly=True)
    terminal_name = fields.Char(string="Terminal", readonly=True)
    pin = fields.Char(string="PIN", readonly=True)
    table = fields.Char(string="Tabla origen", readonly=True)
    event_time = fields.Char(string="Hora del evento", readonly=True)
    attempt = fields.Integer(string="Intentos", readonly=True)
    last_status_code = fields.Integer(string="Último código HTTP", readonly=True)
    last_error = fields.Text(string="Último error", readonly=True)
    created_at = fields.Char(string="Creado", readonly=True)
    next_retry_at = fields.Char(string="Próximo reintento", readonly=True)
    expires_at = fields.Char(string="Expira", readonly=True)
    payload = fields.Text(string="Payload", readonly=True)

    _sql_constraints = [
        (
            "uuid_uniq",
            "unique(uuid)",
            "El reintento ya está registrado",
        ),
    ]

    @api.model
    def action_sync_retries(self):
        client = self.env["api.connect.config"].get_client()
        resp = client.request("GET", "/api/webhook-retries/")
        data = client.check(resp, (200,), "consultar webhooks fallidos")
        rows = data.get("rows") or []
        for row in rows:
            existing = self.search([("uuid", "=", row.get("uuid"))], limit=1)
            vals = {
                "estado": "vivo" if row.get("estado") == "vivo" else "muerto",
                "sn": row.get("sn") or "",
                "terminal_name": row.get("terminal_name") or "",
                "pin": str(row.get("pin") or ""),
                "table": row.get("table") or "",
                "event_time": row.get("event_time") or "",
                "attempt": int(row.get("attempt") or 0),
                "last_status_code": int(row.get("last_status_code") or 0),
                "last_error": str(row.get("last_error") or "")[:2000],
                "created_at": row.get("created_at") or "",
                "next_retry_at": row.get("next_retry_at") or "",
                "expires_at": row.get("expires_at") or "",
                "payload": json.dumps(row.get("payload") or {}, ensure_ascii=False, default=str)[:8000],
            }
            if existing:
                if existing.estado != "reprocesado":
                    existing.write(vals)
            else:
                self.create(vals)
        return self.env["api.connect.config"]._notify(
            _("Webhooks fallidos sincronizados: %s pendientes · %s en dead-letter")
            % (data.get("pending_count"), data.get("dead_count"))
        )

    def action_reprocess(self):
        client_ready = True
        try:
            self.env["api.connect.config"].get_client()
        except UserError:
            client_ready = False
        processed = 0
        failed = 0
        for retry in self:
            try:
                payload = json.loads(retry.payload or "{}")
            except ValueError:
                payload = None
            if not payload:
                failed += 1
                continue
            result = self.env["api.connect.event"].sudo().process_webhook(payload)
            if result.get("status") == 200:
                retry.write({"estado": "reprocesado"})
                processed += 1
            else:
                retry.write({
                    "last_error": "Reproceso falló: %s" % result,
                })
                failed += 1
        if not client_ready:
            raise UserError(_("Configure API Connect antes de reprocesar"))
        return self.env["api.connect.config"]._notify(
            _("Reprocesados: %s · Fallidos: %s") % (processed, failed)
        )
