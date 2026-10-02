{
    "name": "GRG WhatsApp Connector",
    "version": "19.0.1.2.0",
    "category": "Point of Sale",
    "summary": "Send POS receipts and invoices on WhatsApp via QR login (no Meta API)",
    "author": "GoRetailGo",
    "website": "https://goretailgo.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "account", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "views/res_company_views.xml",
        "views/res_company_auto_views.xml",
        "views/account_move_views.xml",
        "views/grg_wa_log_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "grg_whatsapp_connector/static/src/pos/**/*",
        ],
    },
    "installable": True,
    "application": False,
}
