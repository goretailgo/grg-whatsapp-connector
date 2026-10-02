/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

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

export class GrgWaNumberDialog extends Component {
    static template = "grg_whatsapp_connector.NumberDialog";
    static components = { Dialog };
    static props = {
        number: { type: String, optional: true },
        reference: { type: String, optional: true },
        onConfirm: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ number: (this.props.number || "").slice(0, 10), error: "" });
        this.inputRef = useRef("input");
        onMounted(() => this.inputRef.el?.focus());
    }

    onInput(ev) {
        const v = ev.target.value.replace(/\D/g, "").slice(0, 10);
        ev.target.value = v;
        this.state.number = v;
        this.state.error = "";
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            this.confirm();
        }
    }

    confirm() {
        if (!grgWaIsValid(this.state.number)) {
            this.state.error = GRG_WA_INVALID_MSG;
            return;
        }
        this.props.onConfirm(this.state.number);
        this.props.close();
    }
}

patch(TicketScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.grgWaT = useState({ busy: false });
    },

    grgWaAskNumber(initial, reference) {
        return new Promise((resolve) => {
            this.env.services.dialog.add(
                GrgWaNumberDialog,
                {
                    number: grgWaClean(initial),
                    reference: reference || "",
                    onConfirm: (n) => resolve(n),
                },
                { onClose: () => resolve(null) }
            );
        });
    },

    async grgWaSendPast(order) {
        const notify = this.env.services.notification;
        if (!order || this.grgWaT.busy) {
            return;
        }
        if (typeof order.id !== "number") {
            notify.add("Order is not synced yet.", { type: "warning" });
            return;
        }
        const partner = order.partner_id;
        const number = await this.grgWaAskNumber(
            partner && (partner.mobile || partner.phone),
            order.pos_reference || order.name || ""
        );
        if (!number) {
            return;
        }
        this.grgWaT.busy = true;
        try {
            const image = await this.env.services.renderer.toJpeg(
                OrderReceipt,
                { order, basic_receipt: false },
                { addClass: "pos-receipt-print p-3" }
            );
            const sentTo = await this.pos.data.call(
                "pos.order",
                "grg_wa_send_receipt",
                [[order.id], image],
                { number, mode: "resend" }
            );
            notify.add(`Receipt sent on WhatsApp to +${sentTo}`, { type: "success" });
        } catch (e) {
            notify.add(e?.data?.message || e?.message || "Sending failed", {
                type: "danger",
                sticky: true,
            });
        } finally {
            this.grgWaT.busy = false;
        }
    },
});
