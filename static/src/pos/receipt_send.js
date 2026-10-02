/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { useState, onMounted } from "@odoo/owl";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";

const GRG_WA_INVALID_MSG = "Enter a valid 10-digit mobile number (starting with 6-9).";

function grgWaClean(value) {
    let d = String(value || "").replace(/\D/g, "");
    if (d.startsWith("00")) {
        d = d.slice(2);
    }
    if (d.length === 12 && d.startsWith("91")) {
        d = d.slice(2);
    }
    if (d.length === 11 && d.startsWith("0")) {
        d = d.slice(1);
    }
    return d;
}

function grgWaIsValid(value) {
    return /^[6-9]\d{9}$/.test(String(value || ""));
}

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        const partner = this.currentOrder?.partner_id;
        this.grgWa = useState({
            number: grgWaClean(partner && (partner.mobile || partner.phone)),
            busy: false,
            status: "",
            ok: false,
        });
        onMounted(() => {
            if (this.currentOrder?.partner_id && this.grgWaValid()) {
                this.grgWaSend(true);
            }
        });
    },

    grgWaValid() {
        return grgWaIsValid(this.grgWa.number);
    },

    grgWaOnInput(ev) {
        const v = ev.target.value.replace(/\D/g, "").slice(0, 10);
        ev.target.value = v;
        this.grgWa.number = v;
        this.grgWa.status = "";
    },

    async grgWaWaitSynced(order, tries = 20) {
        for (let i = 0; i < tries; i++) {
            if (typeof order.id === "number") {
                return true;
            }
            await new Promise((r) => setTimeout(r, 500));
        }
        return false;
    },

    async grgWaSend(auto = false) {
        if (this.grgWa.busy) {
            return;
        }
        const order = this.currentOrder;
        if (!order) {
            return;
        }
        const number = grgWaClean(this.grgWa.number);
        if (!grgWaIsValid(number)) {
            if (!auto) {
                this.grgWa.ok = false;
                this.grgWa.status = GRG_WA_INVALID_MSG;
            }
            return;
        }
        this.grgWa.busy = true;
        this.grgWa.ok = true;
        this.grgWa.status = "Sending receipt on WhatsApp...";
        try {
            if (!(await this.grgWaWaitSynced(order))) {
                throw new Error("Order not synced yet. Try again.");
            }
            if (typeof this.generateTicketImage !== "function") {
                throw new Error("Receipt image renderer not available.");
            }
            const image = await this.generateTicketImage(false);
            const sentTo = await this.pos.data.call(
                "pos.order",
                "grg_wa_send_receipt",
                [[order.id], image],
                { number, auto }
            );
            if (sentTo) {
                this.grgWa.ok = true;
                this.grgWa.status = `Receipt sent on WhatsApp to +${sentTo}`;
            } else {
                this.grgWa.status = "";
            }
        } catch (e) {
            this.grgWa.ok = false;
            this.grgWa.status = e?.data?.message || e?.message || "Sending failed";
        } finally {
            this.grgWa.busy = false;
        }
    },
});
