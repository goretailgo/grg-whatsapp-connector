import logging
import re

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_URL = "grg_whatsapp_connector.service_url"
PARAM_KEY = "grg_whatsapp_connector.api_key"
PARAM_CC = "grg_whatsapp_connector.default_country_code"

STATE_MAP = {
    "open": "connected",
    "qr": "waiting_scan",
    "connecting": "connecting",
    "reconnecting": "connecting",
}


class ResCompany(models.Model):
    _inherit = "res.company"

    grg_wa_session = fields.Char("WhatsApp Session ID", copy=False, readonly=True)
    grg_wa_state = fields.Selection(
        [
            ("disconnected", "Disconnected"),
            ("waiting_scan", "Waiting for QR scan"),
            ("connecting", "Connecting"),
            ("connected", "Connected"),
        ],
        string="WhatsApp Status",
        default="disconnected",
        copy=False,
        readonly=True,
    )
    grg_wa_number = fields.Char("Connected Number", copy=False, readonly=True)
    grg_wa_qr = fields.Binary("WhatsApp QR", copy=False, readonly=True, attachment=False)

    # ------------------------------------------------------------------
    # Service helpers
    # ------------------------------------------------------------------
    def _grg_wa_request(self, method, path, payload=None, timeout=30):
        ICP = self.env["ir.config_parameter"].sudo()
        base = (ICP.get_param(PARAM_URL) or "http://127.0.0.1:3100").rstrip("/")
        key = ICP.get_param(PARAM_KEY) or ""
        if not key or key == "change-me":
            raise UserError(_("Set system parameter '%s' (same value as API_KEY in service/.env).", PARAM_KEY))
        try:
            resp = requests.request(
                method, base + path, json=payload, headers={"x-api-key": key}, timeout=timeout
            )
        except requests.RequestException as e:
            _logger.exception("WhatsApp service unreachable")
            raise UserError(_("WhatsApp service unreachable at %(url)s: %(err)s", url=base, err=e))
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            raise UserError(
                _("WhatsApp: %(msg)s", msg=data.get("error") or f"HTTP {resp.status_code} {resp.text[:200]}")
            )
        return data

    def _grg_wa_session_id(self):
        self.ensure_one()
        if not self.grg_wa_session:
            sid = re.sub(r"[^A-Za-z0-9_-]", "_", f"{self.env.cr.dbname}_c{self.id}")[:64]
            self.sudo().grg_wa_session = sid
        return self.grg_wa_session

    def _grg_wa_apply(self, data):
        self.ensure_one()
        qr = data.get("qr") or ""
        me = (data.get("me") or "").split("@")[0].split(":")[0]
        state = STATE_MAP.get(data.get("state"), "disconnected")
        self.sudo().write({
            "grg_wa_state": state,
            "grg_wa_qr": qr.split(",", 1)[1] if qr.startswith("data:") else False,
            "grg_wa_number": me if state == "connected" and me else False,
        })

    @api.model
    def _grg_wa_normalize_number(self, raw):
        digits = re.sub(r"\D", "", raw or "")
        cc = self.env["ir.config_parameter"].sudo().get_param(PARAM_CC) or "91"
        if digits.startswith("00"):
            digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:
            digits = cc + digits
        if not 11 <= len(digits) <= 15:
            raise UserError(_("Invalid WhatsApp number: %s", raw or "-"))
        return digits

    def _grg_wa_ensure_connected(self):
        self.ensure_one()
        if not self.grg_wa_session:
            raise UserError(_("WhatsApp is not connected for %s. Go to Settings → Companies → WhatsApp and scan the QR.", self.name))
        self._grg_wa_apply(self._grg_wa_request("GET", f"/sessions/{self.grg_wa_session}/status"))
        if self.grg_wa_state != "connected":
            raise UserError(_("WhatsApp is not connected for %s. Go to Settings → Companies → WhatsApp and scan the QR.", self.name))

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_grg_wa_connect(self):
        self.ensure_one()
        sid = self._grg_wa_session_id()
        self._grg_wa_apply(self._grg_wa_request("POST", f"/sessions/{sid}/connect", {}, timeout=40))
        return True

    def action_grg_wa_refresh(self):
        self.ensure_one()
        if not self.grg_wa_session:
            return self.action_grg_wa_connect()
        self._grg_wa_apply(self._grg_wa_request("GET", f"/sessions/{self.grg_wa_session}/status"))
        return True

    def action_grg_wa_logout(self):
        self.ensure_one()
        if self.grg_wa_session:
            self._grg_wa_request("POST", f"/sessions/{self.grg_wa_session}/logout", {})
        self.sudo().write({"grg_wa_state": "disconnected", "grg_wa_qr": False, "grg_wa_number": False})
        return True
