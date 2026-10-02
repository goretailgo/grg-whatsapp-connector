from odoo import models, _
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = "pos.order"

    def grg_wa_send_invoice(self, number=None):
        self.ensure_one()
        if not self.account_move:
            raise UserError(_("This order has no invoice. Select a customer and enable 'Invoice' before payment."))
        return self.account_move.sudo()._grg_wa_send_pdf(number=number)
