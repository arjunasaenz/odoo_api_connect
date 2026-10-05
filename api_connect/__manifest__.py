{
    "name": "API Connect",
    "summary": "Conector Odoo para terminales de acceso ZKTeco/Hikvision vía API Connect",
    "description": """
Gestión desde Odoo de terminales de control de acceso conectados a API Connect:
- Sincronización y creación de terminales
- Registro de empleados (PIN, tarjeta, rostro) en los terminales
- Recepción de marcaciones por webhook en hr.attendance (idempotente)
""",
    "author": "RentIP Solution",
    "website": "https://rentipsolution.com",
    "category": "Human Resources/Connectors",
    "version": "18.0.3.0.0",
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
