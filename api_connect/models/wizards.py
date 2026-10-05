import random

import base64

import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError

DOOR_SETTINGS_FIELDS = [
    "OpenDelayTime",
    "KeepOpenPeriodDoor",
    "ActivePeriodDoor",
    "VerificationType",
    "SensorType",
    "SensorDelayTime",
    "Reader1IOStatus",
    "Reader2IOStatus",
    "WiegandInID",
    "WiegandOutID",
]

WIEGAND_FIELDS = [
    "total_bits",
    "facility_code",
    "first_parity_bit_position",
    "second_parity_bit_position",
    "odd_bit_start",
    "odd_bit_length",
    "even_bit_start",
    "even_bit_length",
    "card_number_start",
    "card_number_length",
    "facility_code_start",
    "facility_code_length",
]


class ApiConnectDoorSettingsWizard(models.TransientModel):
    _name = "api.connect.door.settings.wizard"
    _description = "API Connect - Configuración de puerta"

    terminal_id = fields.Many2one("api.connect.terminal", string="Terminal", required=True)
    door_number = fields.Integer(string="Puerta", required=True)
    OpenDelayTime = fields.Integer(string="Tiempo de apertura (s)")
    KeepOpenPeriodDoor = fields.Integer(string="Mantener abierta (periodo)")
    ActivePeriodDoor = fields.Integer(string="Periodo activo")
    VerificationType = fields.Integer(string="Tipo de verificación")
    SensorType = fields.Integer(string="Tipo de sensor")
    SensorDelayTime = fields.Integer(string="Retardo del sensor")
    Reader1IOStatus = fields.Integer(string="Estado lector 1")
    Reader2IOStatus = fields.Integer(string="Estado lector 2")
    WiegandInID = fields.Integer(string="Wiegand entrada")
    WiegandOutID = fields.Integer(string="Wiegand salida")
    SuperPassword = fields.Char(string="Super password", password=True)
    DuressPassword = fields.Char(string="Password duress", password=True)

    def action_apply(self):
        self.ensure_one()
        terminal = self.terminal_id
        payload = {"access_door_number": [self.door_number]}
        for fname in DOOR_SETTINGS_FIELDS:
            val = getattr(self, fname)
            if val:
                payload[fname] = val
        if self.SuperPassword:
            payload["SuperPassword"] = self.SuperPassword
        if self.DuressPassword:
            payload["DuressPassword"] = self.DuressPassword
        terminal._call_api_logged(
            _("Configurar puerta %s") % self.door_number,
            lambda c: c.set_door_settings(terminal.sn, payload, terminal.brand),
        )
        return {"type": "ir.actions.act_window_close"}


class ApiConnectWiegandWizard(models.TransientModel):
    _name = "api.connect.wiegand.wizard"
    _description = "API Connect - Formato Wiegand"

    terminal_id = fields.Many2one("api.connect.terminal", string="Terminal", required=True)
    wiegand_format_id_number = fields.Integer(string="ID del formato", default=11, required=True)
    format_name = fields.Char(string="Nombre del formato", required=True)
    total_bits = fields.Integer(string="Bits totales", required=True)
    facility_code = fields.Integer(string="Bits facility code", default=0)
    auto_selection = fields.Boolean(string="Auto selección")
    first_parity_bit_position = fields.Integer(string="Posición paridad 1")
    second_parity_bit_position = fields.Integer(string="Posición paridad 2")
    odd_bit_start = fields.Integer(string="Inicio bits impares")
    odd_bit_length = fields.Integer(string="Longitud bits impares")
    even_bit_start = fields.Integer(string="Inicio bits pares")
    even_bit_length = fields.Integer(string="Longitud bits pares")
    card_number_start = fields.Integer(string="Inicio número de tarjeta")
    card_number_length = fields.Integer(string="Longitud número de tarjeta")
    facility_code_start = fields.Integer(string="Inicio facility code")
    facility_code_length = fields.Integer(string="Longitud facility code")

    def action_set(self):
        self.ensure_one()
        terminal = self.terminal_id
        payload = {
            "wiegand_format_id_number": self.wiegand_format_id_number,
            "format_name": self.format_name,
        }
        for fname in WIEGAND_FIELDS:
            val = getattr(self, fname)
            if val:
                payload[fname] = val
        if self.auto_selection:
            payload["auto_selection"] = True
        terminal._call_api_logged(
            _("Wiegand: definir formato %s") % self.wiegand_format_id_number,
            lambda c: c.set_wiegand(terminal.sn, payload),
        )
        return {"type": "ir.actions.act_window_close"}

    def action_delete(self):
        self.ensure_one()
        terminal = self.terminal_id
        terminal._call_api_logged(
            _("Wiegand: borrar formato %s") % self.wiegand_format_id_number,
            lambda c: c.delete_wiegand(terminal.sn, {
                "wiegand_format_id_number": self.wiegand_format_id_number,
            }),
        )
        return {"type": "ir.actions.act_window_close"}


class ApiConnectMessageWizard(models.TransientModel):
    _name = "api.connect.message.wizard"
    _description = "API Connect - Mensaje en pantalla del terminal"

    terminal_ids = fields.Many2many("api.connect.terminal", string="Terminales", required=True)
    message_id = fields.Integer(string="ID del mensaje", default=1, required=True)
    message = fields.Text(string="Mensaje", required=True)
    type_message = fields.Selection(
        [("1", "Público (todos los usuarios)"), ("2", "Privado (un usuario)")],
        string="Tipo",
        default="1",
        required=True,
    )
    duration = fields.Integer(string="Duración (minutos)", default=60, required=True)
    start_at = fields.Datetime(string="Mostrar desde", default=fields.Datetime.now, required=True)
    pin = fields.Char(string="PIN del usuario (para mensaje privado)")

    def action_send(self):
        self.ensure_one()
        if self.type_message == "2" and not self.pin:
            raise UserError(_("Indica el PIN del usuario para el mensaje privado"))
        for terminal in self.terminal_ids:
            tz = pytz.timezone(terminal.tz or "UTC")
            local_start = pytz.utc.localize(
                fields.Datetime.to_datetime(self.start_at)
            ).astimezone(tz)
            payload = {
                "message_id": self.message_id,
                "message": self.message,
                "type_message": int(self.type_message),
                "message_duration": self.duration,
                "start_date_time": local_start.strftime("%Y-%m-%d %H:%M:%S"),
            }
            terminal._call_api_logged(
                _("Mensaje pantalla (%s)") % ("privado" if self.type_message == "2" else "público"),
                lambda c, p=payload, t=terminal: c.send_message(t.sn, p),
            )
            if self.type_message == "2":
                terminal._call_api_logged(
                    _("Mensaje a usuario %s") % self.pin,
                    lambda c, t=terminal: c.send_message_user(t.sn, {
                        "pin": self.pin,
                        "message_id": self.message_id,
                    }),
                )
        return {"type": "ir.actions.act_window_close"}


class ApiConnectFingerprintWizard(models.TransientModel):
    _name = "api.connect.fingerprint.wizard"
    _description = "API Connect - Registrar huella dactilar"

    employee_id = fields.Many2one("hr.employee", string="Empleado", required=True)
    fp_id = fields.Integer(
        string="ID de huella (1-10)",
        default=1,
        required=True,
        help="Cada usuario admite hasta 10 huellas (IDs 1-10)",
    )
    template_file = fields.Binary(
        string="Plantilla de huella (archivo)",
        required=True,
        help="Archivo de plantilla de huella que se enviará codificado en BASE64",
    )

    def action_register(self):
        self.ensure_one()
        employee = self.employee_id
        if not (1 <= self.fp_id <= 10):
            raise UserError(_("El ID de huella debe estar entre 1 y 10"))
        template = base64.b64decode(self.template_file)
        client = employee._apiconnect_client()
        failures = []
        for terminal in employee.apiconnect_terminal_ids:
            try:
                client.add_fingerprint(
                    terminal.sn,
                    employee.apiconnect_pin,
                    self.fp_id,
                    template.decode("latin-1"),
                )
            except UserError as exc:
                failures.append("%s: %s" % (terminal.sn, exc))
        if failures:
            raise UserError(_("Huella con errores:\n%s") % "\n".join(failures))
        return {"type": "ir.actions.act_window_close"}


class ApiConnectBiodataWizard(models.TransientModel):
    _name = "api.connect.biodata.wizard"
    _description = "API Connect - Registrar datos biométricos"

    employee_id = fields.Many2one("hr.employee", string="Empleado", required=True)
    type_ = fields.Selection(
        [
            ("1", "Huella"),
            ("2", "Rostro"),
            ("3", "Rostro luz visible"),
        ],
        string="Tipo de dato",
        default="1",
        required=True,
    )
    content_file = fields.Binary(
        string="Datos biométricos (archivo)",
        required=True,
        help="Contenido biométrico que se enviará codificado en BASE64",
    )

    def action_register(self):
        self.ensure_one()
        employee = self.employee_id
        content = base64.b64decode(self.content_file)
        client = employee._apiconnect_client()
        failures = []
        for terminal in employee.apiconnect_terminal_ids:
            try:
                client.add_biodata(
                    terminal.sn,
                    employee.apiconnect_pin,
                    int(self.type_),
                    content.decode("latin-1"),
                )
            except UserError as exc:
                failures.append("%s: %s" % (terminal.sn, exc))
        if failures:
            raise UserError(_("Biodata con errores:\n%s") % "\n".join(failures))
        return {"type": "ir.actions.act_window_close"}


class ApiConnectSelfieWizard(models.TransientModel):
    _name = "api.connect.selfie.wizard"
    _description = "API Connect - Invitar a registro por selfie"

    employee_ids = fields.Many2many("hr.employee", string="Empleados", required=True)
    url_redirect = fields.Char(string="URL de redirección tras la selfie (opcional)")
    subject = fields.Char(string="Asunto del email (opcional)")
    message = fields.Text(string="Mensaje del email (opcional)")

    def action_invite(self):
        self.ensure_one()
        client = self.env["api.connect.config"].get_client()
        failures = []
        for employee in self.employee_ids:
            if not employee.apiconnect_pin:
                failures.append("%s: sin PIN API Connect" % employee.name)
                continue
            if not employee.work_email:
                failures.append("%s: sin email de trabajo" % employee.name)
                continue
            sns = employee.apiconnect_terminal_ids.mapped("sn")
            if not sns:
                failures.append("%s: sin terminales asignadas" % employee.name)
                continue
            try:
                client.invite_selfie(
                    sns,
                    employee.work_email,
                    employee.apiconnect_pin,
                    employee.name,
                    url_redirect=self.url_redirect or None,
                )
            except UserError as exc:
                failures.append("%s: %s" % (employee.name, exc))
        if failures:
            raise UserError(_("Invitaciones con errores:\n%s") % "\n".join(failures))
        return {"type": "ir.actions.act_window_close"}


class ApiConnectEmployeeAccessGroupWizard(models.TransientModel):
    _name = "api.connect.employee.accessgroup.wizard"
    _description = "API Connect - Grupo de acceso del empleado"

    employee_ids = fields.Many2many("hr.employee", string="Empleados", required=True)
    access_group_number = fields.Integer(string="Grupo de acceso", default=1, required=True)

    def action_apply(self):
        self.ensure_one()
        client = self.env["api.connect.config"].get_client()
        failures = []
        for employee in self.employee_ids:
            if not employee.apiconnect_pin:
                failures.append("%s: sin PIN API Connect" % employee.name)
                continue
            for terminal in employee.apiconnect_terminal_ids:
                try:
                    client.set_customer_access_group(
                        terminal.sn,
                        employee.apiconnect_pin,
                        self.access_group_number,
                    )
                except UserError as exc:
                    failures.append("%s → %s: %s" % (employee.name, terminal.sn, exc))
        if failures:
            raise UserError(_("Grupos con errores:\n%s") % "\n".join(failures))
        return {"type": "ir.actions.act_window_close"}


class ApiConnectAccessGroupWizard(models.TransientModel):
    _name = "api.connect.access.group.wizard"
    _description = "API Connect - Grupo de acceso (ZKTeco)"

    terminal_id = fields.Many2one("api.connect.terminal", string="Terminal", required=True)
    access_group_id = fields.Integer(string="Número de grupo de acceso", required=True)
    holiday = fields.Char(
        string="Feriados (opcional)",
        help="Definición de feriados del grupo tal como la interpreta el panel",
    )
    tz_format = fields.Char(string="Formato de zona horaria (opcional)")

    def action_apply(self):
        self.ensure_one()
        terminal = self.terminal_id
        if not terminal.api_id:
            raise UserError(
                _("Registre o sincronice la terminal %s primero") % terminal.sn
            )
        payload = {"access_group_id": self.access_group_id}
        if self.holiday:
            payload["holiday"] = self.holiday
        if self.tz_format:
            payload["tz_format"] = self.tz_format
        terminal._call_api_logged(
            _("Grupo de acceso %s") % self.access_group_id,
            lambda c: c.zk_set_access_group(terminal.sn, payload),
        )
        return {"type": "ir.actions.act_window_close"}


class ApiConnectVisitorWizard(models.TransientModel):
    _name = "api.connect.visitor.wizard"
    _description = "API Connect - Registrar visitante"

    terminal_ids = fields.Many2many("api.connect.terminal", string="Terminales", required=True)
    pin = fields.Char(string="PIN del visitante", required=True)
    full_name = fields.Char(string="Nombre completo", required=True)
    qr_number = fields.Char(
        string="Número de QR/tarjeta",
        default=lambda self: str(random.randint(10000000, 99999999)),
    )
    access_group_number = fields.Integer(string="Grupo de acceso", default=1)
    type_visitor = fields.Integer(
        string="Tipo de visitante",
        default=1,
        help="Según el protocolo del terminal (1 permanente, 2 de una entrada...)",
    )
    start_at = fields.Datetime(string="Inicio de acceso")
    end_at = fields.Datetime(string="Fin de acceso")
    doors = fields.Char(
        string="Puertas",
        help="Números de puerta separados por coma (ej: 1,2)",
    )
    verification_count = fields.Integer(string="Cantidad de verificaciones")
    create_link = fields.Boolean(
        string="Generar enlace QR",
        help="La API genera un enlace de registro para el visitante",
    )

    def action_register(self):
        self.ensure_one()
        doors_list = None
        if self.doors:
            try:
                doors_list = [int(x) for x in self.doors.split(",") if x.strip()]
            except ValueError:
                raise UserError(_("Puertas debe ser números separados por coma"))
        for terminal in self.terminal_ids:
            if not terminal.api_id:
                raise UserError(
                    _("Registre o sincronice la terminal %s primero") % terminal.sn
                )
            payload = {
                "pin": self.pin,
                "full_name": self.full_name,
                "qr_number": self.qr_number or "",
                "access_group_number": self.access_group_number,
                "type_visitor": self.type_visitor,
            }
            if self.start_at:
                tz = pytz.timezone(terminal.tz or "UTC")
                payload["start_access_period"] = pytz.utc.localize(
                    fields.Datetime.to_datetime(self.start_at)
                ).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            if self.end_at:
                tz = pytz.timezone(terminal.tz or "UTC")
                payload["end_access_period"] = pytz.utc.localize(
                    fields.Datetime.to_datetime(self.end_at)
                ).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
            if doors_list:
                payload["access_door_number"] = doors_list
            if self.verification_count:
                payload["verification_count"] = self.verification_count
            if self.create_link:
                payload["create_link"] = True
            terminal._call_api_logged(
                _("Visitante %s") % self.full_name,
                lambda c, p=payload, t=terminal: c.create_visitor(t.sn, p),
            )
        return {
            "type": "ir.actions.act_window_close",
        }


class ApiConnectPublicityWizard(models.TransientModel):
    _name = "api.connect.publicity.wizard"
    _description = "API Connect - Imágenes publicitarias"

    terminal_id = fields.Many2one("api.connect.terminal", string="Terminal", required=True)
    url = fields.Char(string="URL de la imagen", required=True)
    index = fields.Integer(string="Índice (posición en pantalla)", default=0)

    def action_load(self):
        self.ensure_one()
        terminal = self.terminal_id
        terminal._call_api_logged(
            _("Publicidad: cargar imagen"),
            lambda c: c.load_publicity(terminal.sn, {"url": self.url, "index": self.index}),
        )
        return {"type": "ir.actions.act_window_close"}
