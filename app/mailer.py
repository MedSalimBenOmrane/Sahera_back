import base64
import ssl, smtplib
from email.message import EmailMessage
from pathlib import Path
from flask import current_app
from app.models import Admin

# URL du site & QR code (image locale pour eviter les blocages des clients mail)
WEBSITE_URL = "https://sahera-webapp.ca"
QR_IMAGE_PATH = Path(__file__).resolve().parent / "assets" / "sahera webapp.png"
WEBSITE_QR_DATA_URI_FALLBACK = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAA+gAAAPoCAYAAABNo9TkAAAQAElEQVR4AezdC5xdVXko8BXRJBJTRUm06lWso1InVrRY9So6wYoWrFABsb0+QPHBK6KitYSaCYpeK5ciCvisVGsVwQpUsHAriQ+8bdGWakahjIqPCiRUsDGYRB6Xb3CEhGRy5ry+/fjzY+XMnLP3+tb3X2vvc77zmnvd7j8CBAgQIECAAAECBAgQIEAgXeBeZaD/6ZwAAQIECBAgQIAAAQIECBDoRKDeBXonGdqGAAECBAgQIECAAAECBAjUQECBPsMkuYkAAQIECBAgQIAAAQIECAxLQIE+LOl7xnENAQIECBAgQIAAAQIECBD4tYAC/dcUTftBPgQIECBAgAABAgQIECBQJwEFep1mq0pjNRYCBAgQIECAAAECBAgQ6KuAAr2vnDrrl4B+CBAgQIAAAQIECBAg0DYBBXrbZly+IaARIECAAAECBAgQIECgcgIK9MpNiQHVX0AGBAgQIECAAAECBAgQmL2AAn32ZvYgkCsgOgECBAgQIECAAAECjRRQoDdyWiVFoHsBexIgQIAAAQIECBAgkCOgQM9xF5VAWwXkTYAAAQIECBAgQIDAdgQU6NuBcTUBAnUUMGYCBAgQIECAAAEC9RVQoNd37oycAIFhC4hHgAABAgQIECBAYIACCvQB4uqaAAECsxGwLQECBAgQIECAQLsFFOjtnn/ZEyDQHgGZEiBAgAABAgQIVFxAgV7xCTI8AgQI1EPAKAkQIECAAAECBHoVUKD3Kmh/AgQIEBi8gAgECBAgQIAAgRYIKNBbMMlSJECAAIGZBdxKgAABAgQIEKiCgAK9CrNgDAQIECDQZAG5ESBAgAABAgQ6ElCgd8RkIwIECBAgUFUB4yJAgAABAgSaIqBAb8pMyoMAAQIECAxCQJ8ECBAgQIDA0AQU6EOjFogAAQIECBDYWsDvBAgQIECAwF0CCvS7LPxEgAABAgQINEtANgQIECBAoFYCCvRaTZfBEiBAgAABAtURMBICBAgQINBfAQV6fz31RoAAAQIECBDoj4BeCBAgQKB1Agr01k25hAkQIECAAAECpTAgQIAAgeoJKNCrNydGRIAAAQIECBCou4DxEyBAgEAXAgr0LtDsQoAAAQIECBAgkCkgNgECBJopoEBv5rzKigABAgQIECBAoFsB+xEgQCBJQIGeBC8sAQIECBAgQIBAOwVkTYAAge0JKNC3J+N6AgQIECBAgAABAvUTMGICBGosoECv8eQZOgECBAgQIECAAIHhCohGgMAgBRTog9TVNwECBAgQIECAAAECnQvYkkDLBRToLV8A0idAgAABAgQIECDQFgF5Eqi6gAK96jNkfAQIECBAgAABAgQI1EHAGAn0LKBA75lQBwQIECBAgAABAgQIEBi0gP7bIKBAb8Msy5EAAQIECBAgQIAAAQIzCbitEgIK9EpMg0EQIECAAAECBAgQIECguQIy60xAgd6Zk60IECBAgAABAgQIECBAoJoCjRmVAr0xUykRAgQIECBAgAABAgQIEOi/wPB6VKAPz1okAgQIECBAgAABAgQIECCwpcDdflOg3w3DjwQIECBAgAABAgQIECBAIEtgEAV6Vi7iEiBAgAABAgQIECBAgACB2grUsEDPsb711lvLjTfeWP7t3/6tnHvuueUTn/iExmCoa+Bv/uZvymWXXVZuuOGGsmnTppwDoaVRJyYmSnbLpJd77vxnzr3YOQLZx1zEz8n8zqgRP7PdOYr2/HvbbbeVDRs2lGuvvbZMTk5qDFLWwPXXX19+8YtflNtvv709B992MlWgbwWzfv368u///u8liqG3vvWt5SUveUn5/d///fLMZz6zPP3pTy8HHHBAOfbYY8vxxx9fXv7yl2sMhrIG/vRP/7S85S1vmVqPsQ6jjY2NlT/8wz8s/+t//a9yyimnlFWrVpXrrrvOiW2rY7pfvy5ZsqRktXhSsF95dNPPIYcckpZ7xO5mzP3aJ+yz5j3i9isP/dRPIOY/q8W6zxSL4z4r94idmfsgY8eT+/FY4V3vetfU44lnP/vZ5YlPfGJ57GMfWx7/+MeXJz/5yVOPd8fueHyhjZUxDkMziDrrSU96Utl9992n1mOsxec973nl1a9+9dRj3Msvv7xVj28V6HecCePZmm9/+9vl9NNPL4cffnhZunRpednLXlbe/e53l7PPPrt88YtfLP/0T/9UrrrqqvLDH/6w/Od//mf58Y9/fMees//fHgS6EYhntaPFuotnt+OdHF/60pfK5z//+fK3f/u35U1velN57nOfW+KBxTve8Y6pYv2//uu/ugllHwIECBAgQKAhAjfddFP56le/WpYvX16e//znlz/+4z+eepEpHt9++ctfLt/85jfL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"
)

_qr_data_uri_cache = None


def _get_qr_data_uri():
    global _qr_data_uri_cache
    if _qr_data_uri_cache:
        return _qr_data_uri_cache

    try:
        with open(QR_IMAGE_PATH, "rb") as qr_file:
            encoded = base64.b64encode(qr_file.read()).decode("ascii")
        _qr_data_uri_cache = f"data:image/png;base64,{encoded}"
    except Exception:
        current_app.logger.exception(
            "Impossible de charger le QR code local (%s), utilisation du fallback embarqué.",
            QR_IMAGE_PATH,
        )
        _qr_data_uri_cache = WEBSITE_QR_DATA_URI_FALLBACK
    return _qr_data_uri_cache


def send_email(to, subject, text_body, html_body=None, reply_to=None, cc=None, bcc=None):
    """
    to: str ou list[str]
    """
    footer_text = (
        "\n\n"
        f"Website : {WEBSITE_URL}\n"
        "QR code : scannez l'image jointe pour ouvrir le site.\n"
    )
    text_with_footer = (text_body or "").rstrip() + footer_text

    html_with_footer = None
    qr_data_uri = _get_qr_data_uri()
    if html_body:
        footer_html = f"""
        <div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;line-height:1.6;color:#111827;">
          <div style="margin-bottom:8px;">Website : <a href="{WEBSITE_URL}" style="color:#2563eb;text-decoration:none;" target="_blank" rel="noopener noreferrer">{WEBSITE_URL}</a></div>
          <div style="display:flex;align-items:center;gap:12px;align-items:flex-start;">
            <img src="{qr_data_uri}" alt="QR code vers Sahera" width="120" height="120" style="border:1px solid #e5e7eb;border-radius:8px;" />
            <div>Scannez le QR code pour ouvrir le site.</div>
          </div>
        </div>
        """
        html_with_footer = f"""{html_body}
{footer_html}"""

    msg = EmailMessage()
    admin_cfg = Admin.query.order_by(Admin.id).first()
    cfg = current_app.config

    sender_email = (
        (admin_cfg.mail_sender_email if admin_cfg else None)
        or (admin_cfg.email if admin_cfg else None)
        or cfg.get("MAIL_SENDER_EMAIL")
    )
    sender_name = (
        (admin_cfg.mail_sender_name if admin_cfg else None)
        or cfg.get("MAIL_SENDER_NAME", "")
    )
    from_header  = f"{sender_name} <{sender_email}>" if sender_name else sender_email

    msg["From"] = from_header
    msg["To"] = ", ".join(to) if isinstance(to, (list, tuple)) else to
    if cc:  msg["Cc"]  = ", ".join(cc)  if isinstance(cc,  (list,tuple)) else cc
    if bcc: # BCC n'apparait pas dans l'entete, mais on l'ajoute a la liste d'envoi plus bas
        pass
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject

    msg.set_content(text_with_footer)
    if html_with_footer:
        msg.add_alternative(html_with_footer, subtype="html")

    host = (admin_cfg.smtp_host if admin_cfg and admin_cfg.smtp_host else None) or cfg.get("SMTP_HOST")
    port = int((admin_cfg.smtp_port if admin_cfg and admin_cfg.smtp_port else None) or cfg.get("SMTP_PORT", 587))
    use_tls = admin_cfg.smtp_use_tls if admin_cfg and admin_cfg.smtp_use_tls is not None else cfg.get("SMTP_USE_TLS", True)
    username = (
        (admin_cfg.smtp_username if admin_cfg and admin_cfg.smtp_username else None)
        or (admin_cfg.email if admin_cfg else None)
        or (cfg.get("SMTP_USERNAME") or "")
    ).strip()
    password = (
        (admin_cfg.smtp_password if admin_cfg and admin_cfg.smtp_password else None)
        or (cfg.get("SMTP_PASSWORD") or "")
    ).strip()

    current_app.logger.info(
        "SMTP: host=%s port=%s tls=%s user=%s pwd_len=%d",
        host,
        port,
        use_tls,
        username,
        len(password)
)
    timeout  = float(current_app.config.get("SMTP_TIMEOUT", 20))

    recipients = []
    for field in ("To","Cc"):
        if msg.get(field):
            recipients.extend([x.strip() for x in msg.get(field).split(",") if x.strip()])
    if bcc:
        if isinstance(bcc, (list,tuple)):
            recipients.extend(bcc)
        else:
            recipients.append(bcc)

    try:
        if use_tls and port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as s:
                if username: s.login(username, password)
                s.send_message(msg, to_addrs=recipients)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as s:
                s.ehlo()
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if username: s.login(username, password)
                s.send_message(msg, to_addrs=recipients)
        return True
    except Exception:
        current_app.logger.exception("Echec d'envoi email")
        return False
