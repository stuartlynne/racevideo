"""Direct delivery of an exported race frame through Gmail SMTP."""
import os
import smtplib
import ssl
import stat
from email.message import EmailMessage
from pathlib import Path


def credentials():
    """Load app-only credentials, with process environment as an override."""
    config=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'racevideo'/'email.env'
    values={}
    if config.exists():
        if stat.S_IMODE(config.stat().st_mode)&0o077:
            raise RuntimeError(f'{config} must only be readable by you; run chmod 600 {config}')
        for raw in config.read_text().splitlines():
            line=raw.strip()
            if not line or line.startswith('#'):continue
            if line.startswith('export '):line=line[7:].lstrip()
            key,separator,value=line.partition('=')
            if separator and key.strip() in ('GMAIL_USER','GMAIL_APP_PASSWORD'):
                value=value.strip()
                if len(value)>=2 and value[0]==value[-1] and value[0] in "'\"":value=value[1:-1]
                values[key.strip()]=value
    sender=os.environ.get('GMAIL_USER',values.get('GMAIL_USER','')).strip()
    password=os.environ.get('GMAIL_APP_PASSWORD',values.get('GMAIL_APP_PASSWORD','')).replace(' ','')
    if not sender or not password:
        raise RuntimeError(f'Add GMAIL_USER and GMAIL_APP_PASSWORD to {config} and run chmod 600 {config}.')
    return sender,password


def send_jpg(recipient, jpg_path, subject, body='Race photo attached.'):
    sender,password=credentials()
    photo=Path(jpg_path)
    message=EmailMessage()
    message['From']=sender
    message['To']=recipient
    message['Subject']=subject
    message.set_content(body)
    message.add_attachment(photo.read_bytes(),maintype='image',subtype='jpeg',filename=photo.name)
    with smtplib.SMTP_SSL('smtp.gmail.com',465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(sender,password)
        smtp.send_message(message)
