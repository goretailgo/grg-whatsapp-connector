import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GrgWaLog(models.Model):
    _name = "grg.wa.log"
    _description = "WhatsApp Message Log"
    _order = "id desc"
    _rec_name = "reference"

    create_date = fields.Datetime("Date", readonly=True)
    reference = fields.Char(required=True, readonly=True)
    doc_type = fields.Selection(
        [("receipt", "POS Receipt"), ("invoice", "Invoice")], string="Type", required=True, readonly=True
    )
    mode = fields.Selection(
        [("auto", "Auto"), ("manual", "Manual"), ("resend", "Resend")], required=True, readonly=True
    )
    state = fields.Selection([("sent", "Sent"), ("failed", "Failed")], required=True, readonly=True)
    number = fields.Char("WhatsApp Number")
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    pos_order_id = fields.Many2one("pos.order", string="POS Order", index=True, ondelete="set null", readonly=True)
    move_id = fields.Many2one("account.move", string="Invoice", ondelete="set null", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True, default=lambda s: s.env.company)
    user_id = fields.Many2one("res.users", string="Sent By", readonly=True, default=lambda s: s.env.user)
    caption = fields.Text(readonly=True)
    error = fields.Text(readonly=True)
    image = fields.Binary("Receipt Image", attachment=True, readonly=True)

    @api.model
    def _grg_log_detached(self, vals):
        """Write a log in its own transaction so it survives the error rollback."""
        try:
            with self.env.registry.cursor() as cr:
                self.env(cr=cr)["grg.wa.log"].sudo().create(vals)
        except Exception:
            _logger.exception("Could not write WhatsApp failure log")

    def action_resend(self):
        sent = []
        for log in self:
            if log.doc_type == "receipt":
                if not log.pos_order_id or not log.image:
                    raise UserError(_("No receipt image stored for %s.", log.reference))
                img = log.image.decode() if isinstance(log.image, bytes) else log.image
                sent.append(log.pos_order_id.sudo()._grg_wa_send_receipt_image(img, log.number, "resend"))
            else:
                if not log.move_id:
                    raise UserError(_("Invoice not found for %s.", log.reference))
                sent.append(log.move_id.sudo()._grg_wa_send_pdf(number=log.number))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": _("Sent to %s", ", ".join(f"+{n}" for n in sent)),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
