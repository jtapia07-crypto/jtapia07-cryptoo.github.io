"""Notificaciones. Nunca lanzan excepciones hacia la API: un fallo de correo no debe romper una confirmación."""
import json, logging, os, smtplib, ssl, urllib.request
from email.message import EmailMessage

log = logging.getLogger("biorifa")

def send_email(to: str, subject: str, body: str, png: bytes | None = None) -> None:
    user = os.getenv("SMTP_USER")
    if not user:
        return log.info("[EMAIL simulado] %s: %s", to, subject)
    try:
        m = EmailMessage(); m["From"] = user; m["To"] = to; m["Subject"] = subject; m.set_content(body)
        if png: m.add_attachment(png, maintype="image", subtype="png", filename="comprobante-qr.png")
        with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", ""), int(os.getenv("SMTP_PORT", 465)),
                              context=ssl.create_default_context(), timeout=15) as s:
            s.login(user, os.environ["SMTP_PASS"]); s.send_message(m)
    except Exception:
        log.exception("Fallo al enviar email a %s", to)

def send_whatsapp(phone: str, text: str) -> None:
    tok, pid = os.getenv("WA_TOKEN"), os.getenv("WA_PHONE_ID")
    if not tok:
        return log.info("[WHATSAPP simulado] %s: %s", phone, text[:60])
    try:
        req = urllib.request.Request(
            f"https://graph.facebook.com/v20.0/{pid}/messages",
            data=json.dumps({"messaging_product": "whatsapp", "to": phone.lstrip("+"), "type": "text",
                             "text": {"body": text}}).encode(),
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        log.exception("Fallo WhatsApp a %s", phone)

def send_instagram(handle: str, text: str) -> None:
    """La API de Instagram no permite iniciar conversaciones: queda en el log para envío manual."""
    if handle: log.warning("[INSTAGRAM manual pendiente] %s: %s", handle, text[:80])
