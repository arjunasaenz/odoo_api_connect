import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import requests
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
TOKEN_TTL_MINUTES = 25
_TOKEN_CACHE = {}


def _utcnow():
    return datetime.now(timezone.utc)


class ApiConnectClient:

    def __init__(self, base_url, username, password, cache_key):
        self.base_url = (base_url or "").rstrip("/")
        self.username = username
        self.password = password
        self.cache_key = cache_key

    @staticmethod
    def _detail(resp):
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300]
        if isinstance(data, dict):
            detail = data.get("detail")
            if detail:
                return str(detail)[:300]
            return json.dumps(data)[:300]
        return str(data)[:300]

    def _login(self):
        if not self.base_url or not self.username or not self.password:
            raise UserError(_(
                "Complete la configuración de API Connect "
                "(URL, usuario y contraseña) antes de continuar."
            ))
        try:
            resp = requests.post(
                "%s/token" % self.base_url,
                json={"username": self.username, "password": self.password},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise UserError(_("No se pudo conectar con API Connect: %s") % exc) from exc
        if resp.status_code != 200:
            raise UserError(
                _("Login fallido en API Connect (%s): %s")
                % (resp.status_code, self._detail(resp))
            )
        token = resp.json().get("access_token")
        if not token:
            raise UserError(_("API Connect no devolvió un token de acceso"))
        _TOKEN_CACHE[self.cache_key] = (token, _utcnow() + timedelta(minutes=TOKEN_TTL_MINUTES))
        return token

    def _get_token(self):
        cached = _TOKEN_CACHE.get(self.cache_key)
        if cached and cached[1] > _utcnow():
            return cached[0]
        return self._login()

    def request(self, method, path, payload=None, params=None, retry_auth=True):
        token = self._get_token()
        try:
            resp = requests.request(
                method,
                "%s%s" % (self.base_url, path),
                json=payload,
                params=params,
                headers={"Authorization": "Bearer %s" % token},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise UserError(_("Error de red llamando a API Connect: %s") % exc) from exc
        if resp.status_code == 401 and retry_auth:
            _TOKEN_CACHE.pop(self.cache_key, None)
            return self.request(method, path, payload=payload, params=params, retry_auth=False)
        return resp

    def check(self, resp, ok_codes=(200, 201), context=""):
        if resp.status_code in ok_codes:
            try:
                return resp.json()
            except ValueError:
                return {}
        raise UserError(
            _("API Connect rechazó %s (%s): %s")
            % (context or "la llamada", resp.status_code, self._detail(resp))
        )

    def list_terminals(self):
        result = []
        skip = 0
        while True:
            resp = self.request("GET", "/terminal/", params={"skip": skip, "limit": 1000})
            if resp.status_code == 404:
                return result
            batch = self.check(resp, (200,), "listar terminales")
            if not batch:
                return result
            result.extend(batch)
            if len(batch) < 1000:
                return result
            skip += 1000

    def create_terminal(self, vals):
        return self.check(
            self.request("POST", "/terminal/", payload=vals),
            (200, 201),
            "crear terminal %s" % vals.get("sn"),
        )

    def last_sync(self, sn):
        resp = self.request("GET", "/terminal/last_sync/%s" % sn)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("message") if "message" in data else None

    def create_customer(self, sn, vals):
        return self.check(
            self.request("POST", "/customer/%s" % sn, payload=vals),
            (200, 201),
            "registrar %s en %s" % (vals.get("pin"), sn),
        )

    def delete_customer(self, sn, pin):
        resp = self.request("DELETE", "/customer/%s/%s" % (sn, pin))
        if resp.status_code == 404:
            return {}
        return self.check(resp, (200, 201), "eliminar %s de %s" % (pin, sn))

    def add_card(self, sn, pin, card_number):
        return self.check(
            self.request("POST", "/customer/card/%s" % sn, payload={
                "pin": pin,
                "card_number": card_number,
            }),
            (200, 201),
            "tarjeta %s en %s" % (pin, sn),
        )

    def add_biophoto(self, sn, pin, photo_url):
        return self.check(
            self.request("POST", "/customer/biophoto/%s" % sn, payload={
                "pin": pin,
                "url": photo_url,
                "type_": 1,
            }),
            (200, 201),
            "rostro %s en %s" % (pin, sn),
        )

    def add_photo(self, sn, pin, img_base64):
        return self.check(
            self.request("POST", "/customer/photo/%s" % sn, payload={
                "pin": pin,
                "imgBase64": img_base64,
            }),
            (200, 201),
            "foto %s en %s" % (pin, sn),
        )


class ApiConnectConfig(models.Model):
    _name = "api.connect.config"
    _description = "API Connect - Configuración"
    _order = "id"

    base_url = fields.Char(
        string="URL de API Connect",
        default="https://api-connect.rentipsolution.com",
    )
    username = fields.Char(string="Usuario")
    password = fields.Char(string="Contraseña")
    webhook_secret = fields.Char(
        string="Secret del webhook",
        readonly=True,
        copy=False,
        default=lambda self: secrets.token_urlsafe(32),
    )
    webhook_url_display = fields.Char(
        string="URL del webhook en Odoo",
        compute="_compute_webhook_url_display",
    )

    @api.model
    def get_singleton(self):
        cfg = self.search([], limit=1)
        if not cfg:
            cfg = self.create({})
        return cfg

    @api.model
    def get_client(self):
        return self.get_singleton()._client()

    @api.model
    def _webhook_base_url(self):
        icp = self.env["ir.config_parameter"].sudo()
        return (
            icp.get_param("api_connect.web_base_url")
            or icp.get_param("web.base.url")
            or ""
        ).rstrip("/")

    def _webhook_url(self):
        return "%s/api_connect/webhook" % self._webhook_base_url()

    def _compute_webhook_url_display(self):
        for cfg in self:
            cfg.webhook_url_display = cfg._webhook_url()

    def _client(self):
        self.ensure_one()
        return ApiConnectClient(self.base_url, self.username, self.password, self.id)

    def action_open_config(self):
        cfg = self.get_singleton()
        return {
            "type": "ir.actions.act_window",
            "res_model": "api.connect.config",
            "res_id": cfg.id,
            "view_mode": "form",
            "target": "current",
        }

    def _notify(self, message, msg_type="success"):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("API Connect"),
                "message": message,
                "type": msg_type,
                "sticky": msg_type != "success",
            },
        }

    def action_test_connection(self):
        self.ensure_one()
        client = self._client()
        data = client.list_terminals()
        return self._notify(_("Conexión correcta. Terminales visibles: %s") % len(data))

    def action_register_webhook(self):
        self.ensure_one()
        url = self._webhook_url()
        if not self.webhook_secret:
            raise UserError(_("No hay secret de webhook configurado"))
        client = self._client()
        payload = {
            "webhook_url": url,
            "webhook_token": self.webhook_secret,
            "webhook_enabled": True,
        }
        resp = client.request("PUT", "/settings/", payload=payload)
        if resp.status_code == 404:
            resp = client.request("POST", "/settings/", payload=payload)
        self.check(resp, (200, 201), "registrar el webhook")
        return self._notify(_("Webhook registrado en API Connect: %s") % url)

    def action_rotate_webhook_secret(self):
        self.ensure_one()
        self.write({"webhook_secret": secrets.token_urlsafe(32)})
        return self._notify(
            _("Secret rotado. Vuelve a ejecutar 'Registrar webhook en API Connect'."),
            "warning",
        )

    def action_sync_terminals(self):
        self.ensure_one()
        self.env["api.connect.terminal"].action_sync_from_api()
        return self._notify(_("Terminales sincronizadas desde API Connect"))
