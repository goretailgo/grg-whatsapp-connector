import logging

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    grg_wa_auto_send = fields.Boolean("Auto-send POS receipt", default=True)


class PosOrder(models.Model):
    _inherit = "pos.order"

    grg_wa_receipt_sent = fields.Boolean("Receipt sent on WhatsApp", copy=False, readonly=True)
    grg_wa_log_ids = fields.One2many("grg.wa.log", "pos_order_id", string="WhatsApp Log")

    def grg_wa_send_receipt(self, image_b64, number=None, auto=False, mode=None):
        """Called from POS. Returns the number used, or False if auto-send was skipped."""
        self.ensure_one()
        order = self.sudo()
        if auto and (
            not order.company_id.grg_wa_auto_send or order.grg_wa_receipt_sent or not order.partner_id
        ):
            return False
        return order._grg_wa_send_receipt_image(image_b64, number, mode or ("auto" if auto else "manual"))

    def _grg_wa_send_receipt_image(self, image_b64, number, mode):
        self.ensure_one()
        company = self.company_id
        partner = self.partner_id
        if image_b64 and image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        vals = {
            "reference": self.pos_reference or self.name,
            "doc_type": "receipt",
            "mode": mode,
            "pos_order_id": self.id,
            "partner_id": partner.id,
            "company_id": company.id,
            "user_id": self.env.uid,
            "number": number or False,
            "image": image_b64 or False,
        }
        try:
            if not image_b64:
                raise UserError(_("Receipt image could not be generated."))
            raw = number
            if not raw and partner:
                raw = (partner.mobile if "mobile" in partner._fields else False) or partner.phone
            if not raw:
                raise UserError(_("Enter the customer's WhatsApp number."))
            to = company._grg_wa_normalize_number(raw)
            vals["number"] = to
            company._grg_wa_ensure_connected()
            greeting = f"Hi {partner.name}," if partner else "Hi,"
            caption = (
                f"{greeting}\nThank you for shopping at {company.name}.\n"
                f"Receipt: {self.pos_reference or self.name}\n"
                f"Amount: {self.currency_id.symbol} {self.amount_total:,.2f}"
            )
            vals["caption"] = caption
            company._grg_wa_request(
                "POST",
                f"/sessions/{company.grg_wa_session}/send-image",
                {"number": to, "base64": image_b64, "mimetype": "image/jpeg", "caption": caption},
                timeout=120,
            )
        except UserError as e:
            vals.update(state="failed", error=e.args[0] if e.args else str(e))
            self.env["grg.wa.log"]._grg_log_detached(vals)
            raise
        vals["state"] = "sent"
        self.env["grg.wa.log"].sudo().create(vals)
        self.write({"grg_wa_receipt_sent": True})
        _logger.info("POS receipt %s sent on WhatsApp (%s) to %s", self.name, mode, to)
        return to
