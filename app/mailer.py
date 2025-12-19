import ssl, smtplib
from email.message import EmailMessage
from flask import current_app
from app.models import Admin

WEBSITE_URL = "https://sahera-webapp.ca"
WEBSITE_QR_URL = "https://chart.googleapis.com/chart?chs=220x220&cht=qr&chl=https%3A%2F%2Fsahera-webapp.ca&choe=UTF-8"


def send_email(to, subject, text_body, html_body=None, reply_to=None, cc=None, bcc=None):
    """
    to: str ou list[str]
    """
    footer_text = (
        "\n\n"
        f"Website : {WEBSITE_URL}\n"
        f"QR code (ouvre le site) : {WEBSITE_QR_URL}\n"
    )
    text_with_footer = (text_body or "").rstrip() + footer_text

    html_with_footer = None
    if html_body:
        footer_html = f"""
        <div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;line-height:1.6;color:#111827;">
          <div style="margin-bottom:8px;">Website : <a href="{WEBSITE_URL}" style="color:#2563eb;text-decoration:none;" target="_blank" rel="noopener noreferrer">{WEBSITE_URL}</a></div>
          <div style="display:flex;align-items:center;gap:12px;align-items:flex-start;">
            <img src="{WEBSITE_QR_URL}" alt="QR code vers Sahera" width="120" height="120" style="border:1px solid #e5e7eb;border-radius:8px;" />
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
    if bcc: # BCC n'apparaît pas dans l'entête, mais on l’ajoute à la liste d'envoi plus bas
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
        current_app.logger.exception("Échec d'envoi email")
        return False
