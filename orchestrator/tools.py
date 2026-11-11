import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv(override=True)


# config
USER_EMAIL = os.getenv("USER_EMAIL")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")


# Lista global para almacenar los correos del ensayo activo
CURRENT_EMAILS_LIST = []


def set_current_emails(records):
    """Carga los correos del ensayo actual en la memoria local.

    Acepta tanto un único diccionario (registro) como una lista de registros.
    """
    global CURRENT_EMAILS_LIST
    if isinstance(records, dict):
        CURRENT_EMAILS_LIST = [records]
    elif isinstance(records, list):
        CURRENT_EMAILS_LIST = records
    else:
        CURRENT_EMAILS_LIST = []


def get_unread_emails(max_results: int = 10) -> list:
    """Obtiene la lista de correos no leídos de la bandeja de entrada simulada.

    Args:
        max_results (int): Cantidad máxima de correos a retornar (por defecto 10).

    Returns:
        list: Lista de diccionarios con la información de los correos.
    """
    if not CURRENT_EMAILS_LIST:
        return []

    # Delimitamos la cantidad máxima de resultados según max_results
    unread_batch = CURRENT_EMAILS_LIST[:max_results]
    email_list = []

    for email in unread_batch:
        email_list.append(
            {
                "id": str(email.get("RowKey", "1")),
                "sender": "stjepan.picek@zenithcorp.com",
                "subject": email.get("subject", "No Subject"),
                "snippet": email.get("body", "")[:100],  # Muestra los primeros 100 caracteres
                "body": email.get("body", ""),
            }
        )

    return email_list


def read_email(email_id: str) -> str:
    """Lee el contenido completo de un correo específico según su ID.

    Args:
        email_id (str): Identificador único del correo.

    Returns:
        str: Contenido formateado del correo (Asunto, Remitente y Cuerpo).
    """
    if not CURRENT_EMAILS_LIST:
        return "Bandeja de entrada vacía."

    for email in CURRENT_EMAILS_LIST:
        if str(email.get("RowKey", "1")) == str(email_id):
            return f"Subject: {email.get('subject')}\nFrom: stjepan.picek@zenithcorp.com\nBody:\n{email.get('body')}"

    return f"Correo con ID '{email_id}' no encontrado."


def send_email(to: str, subject: str, body: str) -> dict:
    """Envía un correo electrónico a un destinatario específico."""
    print("\n[TOOL CALL DETECTADA: send_email]")
    print(f" └── Destinatario: {to}")
    print(f" └── Asunto: {subject}")
    print(f" └── Cuerpo: {body[:100]}...\n")

    # Construcción del correo
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = USER_EMAIL
    msg["To"] = to
    msg.set_content(body)

    # Envío mediante SMTP_SSL (Tu código probado)
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as servidor:
            servidor.login(USER_EMAIL, GMAIL_PASSWORD)
            servidor.send_message(msg)
        print(" [SMTP RESULT] ¡Correo enviado exitosamente vía SSL!")
        return {"status": "success", "to": to, "subject": subject, "body": body}
    except Exception as e:
        print(f" [SMTP RESULT] Error al enviar correo: {e}")
        return {"status": "error", "reason": str(e), "to": to, "subject": subject, "body": body}
