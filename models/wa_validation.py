import re

from odoo import api, models, _
from odoo.exceptions import UserError

INVALID_MSG = "Enter a valid 10-digit mobile number (starting with 6-9)."


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model
    def _grg_wa_normalize_number(self, raw):
        cc = self.env["ir.config_parameter"].sudo().get_param(
            "grg_whatsapp_connector.default_country_code"
        ) or "91"
        digits = re.sub(r"\D", "", raw or "")
        if digits.startswith("00"):
            digits = digits[2:]
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10 + len(cc) and digits.startswith(cc):
            digits = digits[len(cc):]
        if cc == "91":
            if not re.fullmatch(r"[6-9]\d{9}", digits):
                raise UserError(_("%(msg)s Got: %(raw)s", msg=INVALID_MSG, raw=raw or "-"))
            return cc + digits
        if len(digits) == 10:
            return cc + digits
        if not 11 <= len(digits) <= 15:
            raise UserError(_("Invalid WhatsApp number: %s", raw or "-"))
        return digits
