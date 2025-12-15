import ssl, smtplib
from email.message import EmailMessage
from flask import current_app



def send_email(to, subject, text_body, html_body=None, reply_to=None, cc=None, bcc=None):
    """
    to: str ou list[str]
    """
    msg = EmailMessage()
    sender_email = current_app.config.get("MAIL_SENDER_EMAIL")
    sender_name  = current_app.config.get("MAIL_SENDER_NAME", "")
    from_header  = f"{sender_name} <{sender_email}>" if sender_name else sender_email

    msg["From"] = from_header
    msg["To"] = ", ".join(to) if isinstance(to, (list, tuple)) else to
    if cc:  msg["Cc"]  = ", ".join(cc)  if isinstance(cc,  (list,tuple)) else cc
    if bcc: # BCC n'apparaît pas dans l'entête, mais on l’ajoute à la liste d'envoi plus bas
        pass
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject

    msg.set_content(text_body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    host = current_app.config["SMTP_HOST"]
    port = int(current_app.config["SMTP_PORT"])
    use_tls = current_app.config.get("SMTP_USE_TLS", True)
    # yourapp/mailer.py
    username = (current_app.config.get("SMTP_USERNAME") or "").strip()
    password = (current_app.config.get("SMTP_PASSWORD") or "").strip()

    current_app.logger.info(
        "SMTP: host=%s port=%s tls=%s user=%s pwd_len=%d",
        current_app.config.get("SMTP_HOST"),
        current_app.config.get("SMTP_PORT"),
        current_app.config.get("SMTP_USE_TLS"),
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