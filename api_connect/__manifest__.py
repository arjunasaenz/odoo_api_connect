{
    "name": "API Connect",
    "summary": "Conector Odoo para terminales de acceso ZKTeco/Hikvision v?a API Connect",
    "description": """
Gesti?n desde Odoo de terminales de control de acceso conectados a API Connect:
- Sincronizaci?n y creaci?n de terminales
- Registro de empleados (PIN, tarjeta, rostro) en los terminales
- Recepci?n de marcaciones por webhook en hr.attendance (idempotente)
""",
    "author": "RentIP Solution",
    "website": "https://rentipsolution.com",
    "category": "Human Resources/Connectors",
    "version": "18.0.1.4.0",
    "license": "LGPL-3",
    "depends": ["hr", "hr_attendance"],
    "data": [
        "security/api_connect_security.xml",
        "security/ir.model.access.csv",
        "views/apiconnect_wizards.xml",
        "views/apiconnect_views.xml",
        "views/hr_employee_views.xml",
        "data/ir_cron.xml",
    ],
    "application": True,
    "installable": True,
}
