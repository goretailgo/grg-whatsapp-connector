import base64

from odoo import models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def _grg_wa_send_pdf(self, number=None):
        """Render the invoice PDF and send it on WhatsApp. Returns the number used."""
        self.ensure_one()
        if self.state != "posted":
            raise UserError(_("Only posted invoices can be sent on WhatsApp."))
        company = self.company_id.sudo()
        company._grg_wa_ensure_connected()

        partner = self.partner_id
        raw = number or (partner.mobile if "mobile" in partner._fields else False) or partner.phone
        if not raw:
            raise UserError(_("Customer %s has no mobile number.", partner.display_name or "-"))
        to = company._grg_wa_normalize_number(raw)

        pdf = self.env["ir.actions.report"].sudo()._render_qweb_pdf("account.account_invoices", self.ids)[0]
        caption = _(
            "Hi %(name)s,\nThank you for shopping at %(company)s.\nInvoice: %(inv)s\nAmount: %(amt)s",
            name=partner.name or "",
            company=company.name,
            inv=self.name,
            amt=f"{self.currency_id.symbol} {self.amount_total:,.2f}",
        )
        company._grg_wa_request(
            "POST",
            f"/sessions/{company.grg_wa_session}/send-document",
            {
                "number": to,
                "base64": base64.b64encode(pdf).decode(),
                "fileName": f"{self.name.replace('/', '_')}.pdf",
                "mimetype": "application/pdf",
                "caption": caption,
            },
            timeout=120,
        )
        self.message_post(body=_("Invoice PDF sent on WhatsApp to +%s", to))
        return to

    def action_grg_wa_send(self):
        sent = [move._grg_wa_send_pdf() for move in self]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": _("Invoice sent to %s", ", ".join(f"+{n}" for n in sent)),
                "type": "success",
                "sticky": False,
            },
        }
