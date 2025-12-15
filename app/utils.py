import secrets, string, bcrypt
from datetime import datetime, timedelta
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app
from .mailer import send_email

def _serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt="register-otp")

def _generate_otp(n=5) -> str:
    return ''.join(secrets.choice(string.digits) for _ in range(n))

def _hash(s: str) -> str:
    return bcrypt.hashpw(s.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def _check_hash(s: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(s.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False
