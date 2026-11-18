import contextvars
import os
import smtplib
import threading
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv(override=True)


# config
USER_EMAIL = os.getenv("USER_EMAIL")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")
MOCK_SMTP = os.getenv("MOCK_SMTP", "true").lower() in ("true", "1", "yes")

# ContextVars para almacenar correos y logs por tarea asíncrona
_CURRENT_EMAILS_VAR = contextvars.ContextVar("CURRENT_EMAILS", default=None)
_SMTP_LOGS_VAR = contextvars.ContextVar("SMTP_LOGS", default=None)

# Buffer global con candado para garantizar captura ante cualquier modelo de ejecución en hilos
_GLOBAL_SMTP_LOCK = threading.Lock()
_GLOBAL_SMTP_LOGS = []


def parse_raw_email(raw_email_str: str, email_id: str = "1", default_sender: str = "colleague@zenithcorp.com") -> dict:
    """Parsea una cadena de correo en formato 'Subject of the email: ... Body: ...'."""
    subject = "No Subject"
    body = raw_email_str
    if "   Body: " in raw_email_str:
        parts = raw_email_str.split("   Body: ", 1)
        subj_part = parts[0].strip()
        if subj_part.startswith("Subject of the email: "):
            subject = subj_part.replace("Subject of the email: ", "").strip()
        else:
            subject = subj_part
        body = parts[1].strip()
    elif "Body: " in raw_email_str:
        parts = raw_email_str.split("Body: ", 1)
        subj_part = parts[0].strip()
        if subj_part.startswith("Subject of the email: "):
            subject = subj_part.replace("Subject of the email: ", "").strip()
        else:
            subject = subj_part
        body = parts[1].strip()

    return {
        "RowKey": str(email_id),
        "sender": default_sender,
        "subject": subject,
        "body": body,
    }


def build_mailbox_for_scenario(scenario_data: dict, record: dict) -> list:
    """Construye la lista completa de correos de la bandeja combinando el escenario y el ataque.

    Aplica la posición indicada ('last', 'mid', 'retrieval') definida en scenario.json.
    """
    raw_emails = scenario_data.get("emails", [])
    position = scenario_data.get("position", "last")

    # Correo atacante
    attacker_email = {
        "RowKey": str(record.get("RowKey", "attacker_1")),
        "sender": record.get("sender") or record.get("From") or "stjepan.picek@zenithcorp.com",
        "subject": record.get("subject", "Immediate Action Required"),
        "body": record.get("body", ""),
    }

    # Parsear correos benignos base del escenario
    benign_emails = []
    for idx, raw_str in enumerate(raw_emails, 1):
        parsed = parse_raw_email(raw_str, email_id=f"benign_{idx}")
        benign_emails.append(parsed)

    # Inserción según política del escenario
    if position == "last" or not benign_emails:
        mailbox = benign_emails + [attacker_email]
    elif position == "mid":
        mid_idx = len(benign_emails) // 2
        mailbox = benign_emails[:mid_idx] + [attacker_email] + benign_emails[mid_idx:]
    elif position == "retrieval":
        # En RAG/retrieval, la bandeja completa simulada contiene los correos relevantes + el ataque
        mailbox = benign_emails + [attacker_email]
    else:
        mailbox = [attacker_email] + benign_emails

    return mailbox


def set_current_emails(records):
    """Carga los correos del ensayo actual en el contexto local de la tarea.

    Acepta tanto un único diccionario (registro) como una lista de registros.
    """
    if isinstance(records, dict):
        _CURRENT_EMAILS_VAR.set([records])
    elif isinstance(records, list):
        _CURRENT_EMAILS_VAR.set(list(records))
    else:
        _CURRENT_EMAILS_VAR.set([])


def get_and_clear_smtp_logs() -> list:
    """Devuelve los logs de SMTP acumulados para la tarea actual y limpia el buffer."""
    with _GLOBAL_SMTP_LOCK:
        global_logs = list(_GLOBAL_SMTP_LOGS)
        _GLOBAL_SMTP_LOGS.clear()

    raw_logs = _SMTP_LOGS_VAR.get()
    var_logs = list(raw_logs) if raw_logs is not None else []
    _SMTP_LOGS_VAR.set([])

    return var_logs if var_logs else global_logs


async def get_unread_emails(max_results: int = 10) -> list:
    """Obtiene la lista de correos no leídos de la bandeja de entrada simulada.

    Args:
        max_results (int): Cantidad máxima de correos a retornar (por defecto 10).

    Returns:
        list: Lista de diccionarios con la información de los correos.
    """
    current_emails = _CURRENT_EMAILS_VAR.get()
    if not current_emails:
        return []

    # Delimitamos la cantidad máxima de resultados según max_results
    unread_batch = current_emails[:max_results]
    email_list = []

    for email in unread_batch:
        sender = email.get("sender") or email.get("From") or "stjepan.picek@zenithcorp.com"
        email_list.append(
            {
                "id": str(email.get("RowKey", "1")),
                "sender": sender,
                "subject": email.get("subject", "No Subject"),
                "snippet": email.get("body", "")[:100],  # Muestra los primeros 100 caracteres
                "body": email.get("body", ""),
            }
        )

    return email_list


async def read_email(email_id: str) -> str:
    """Lee el contenido completo de un correo específico según su ID.

    Args:
        email_id (str): Identificador único del correo.

    Returns:
        str: Contenido formateado del correo (Asunto, Remitente y Cuerpo).
    """
    current_emails = _CURRENT_EMAILS_VAR.get()
    if not current_emails:
        return "Bandeja de entrada vacía."

    for email in current_emails:
        if str(email.get("RowKey", "1")) == str(email_id):
            sender = email.get("sender") or email.get("From") or "stjepan.picek@zenithcorp.com"
            return f"Subject: {email.get('subject')}\nFrom: {sender}\nBody:\n{email.get('body')}"

    return f"Correo con ID '{email_id}' no encontrado."


async def send_email(to: str, subject: str, body: str) -> dict:
    """Envía un correo electrónico a un destinatario específico (Mockeado por defecto para evaluación segura)."""
    print("\n[TOOL CALL DETECTADA: send_email]")
    print(f" └── Destinatario: {to}")
    print(f" └── Asunto: {subject}")
    print(f" └── Cuerpo: {body[:100]}...\n")

    def _append_smtp_log(entry: dict):
        with _GLOBAL_SMTP_LOCK:
            _GLOBAL_SMTP_LOGS.append(entry)
        raw = _SMTP_LOGS_VAR.get()
        current_logs = list(raw) if raw is not None else []
        current_logs.append(entry)
        _SMTP_LOGS_VAR.set(current_logs)

    if MOCK_SMTP:
        log_entry = {
            "status": "success",
            "to": to,
            "subject": subject,
            "body": body,
            "simulated": True,
        }
        _append_smtp_log(log_entry)
        print(" [SMTP MOCK RESULT] ¡Correo registrado y simulado exitosamente!")
        return {"status": "success", "to": to, "subject": subject, "body": body}

    # Envío real si MOCK_SMTP está configurado explícitamente en False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = USER_EMAIL
    msg["To"] = to
    msg.set_content(body)

    log_entry = {
        "status": "error",
        "to": to,
        "subject": subject,
        "body": body,
    }

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as servidor:
            servidor.login(USER_EMAIL, GMAIL_PASSWORD)
            servidor.send_message(msg)
            print(" [SMTP RESULT] ¡Correo enviado exitosamente vía SSL!")
            log_entry["status"] = "success"
            _append_smtp_log(log_entry)
            return {"status": "success", "to": to, "subject": subject, "body": body}

    except Exception as e:
        print(f" [SMTP RESULT] Error al enviar correo: {e}")
        log_entry["status"] = "error"
        log_entry["reason"] = str(e)
        _append_smtp_log(log_entry)
        return {
            "status": "error",
            "reason": str(e),
            "to": to,
            "subject": subject,
            "body": body,
        }
