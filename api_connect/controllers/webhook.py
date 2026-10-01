import base64
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ApiConnectWebhookController(http.Controller):

    def _check_secret(self, provided):
        cfg = request.env["api.connect.config"].sudo().get_singleton()
        secret = cfg.webhook_secret
        if not secret:
            return False
        return hmac.compare_digest(provided or "", "Bearer %s" % secret)

    @http.route(
        "/api_connect/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
        readonly=False,
    )
    def webhook(self):
        req = request.httprequest
        raw = req.get_data()
        try:
            payload = json.loads(raw)
        except ValueError:
            return request.make_response(
                json.dumps({"status": 400, "error": "json inválido"}),
                status=400,
                headers={"Content-Type": "application/json"},
            )
        if not self._check_secret(req.headers.get("Authorization", "")):
            _logger.warning("API Connect webhook: intento con token inválido")
            return request.make_response(
                json.dumps({"status": 401, "error": "unauthorized"}),
                status=401,
                headers={"Content-Type": "application/json"},
            )
        try:
            result = request.env["api.connect.event"].sudo().process_webhook(payload)
        except Exception:
            _logger.exception("API Connect webhook: error no controlado")
            result = {"status": 500, "error": "error interno"}
        return request.make_response(
            json.dumps(result),
            status=result.get("status", 200),
            headers={"Content-Type": "application/json"},
        )

    @http.route(
        "/api_connect/employee_photo/<string:secret>/<int:employee_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
        readonly=True,
    )
    def employee_photo(self, secret=None, employee_id=0):
        cfg = request.env["api.connect.config"].sudo().get_singleton()
        if not cfg.webhook_secret or not secret or not hmac.compare_digest(
            secret, cfg.webhook_secret
        ):
            return request.make_response("forbidden", status=403)
        employee = request.env["hr.employee"].sudo().browse(employee_id).exists()
        if not employee or not employee.image_1920:
            return request.make_response("not found", status=404)
        data = base64.b64decode(employee.image_1920)
        content_type = "image/png" if data[:8] == PNG_MAGIC else "image/jpeg"
        return request.make_response(
            data, headers={"Content-Type": content_type}
        )
