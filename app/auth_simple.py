# app/auth_simple.py
from functools import wraps
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from flask import request, jsonify, g, current_app
import jwt  # PyJWT (déjà utilisé chez toi)

# Blacklist simple en mémoire (tu peux la stocker en DB si tu veux)
TOKEN_BLACKLIST = set()

def _get_bearer_token():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None

def issue_token(user_id: int | str, role: str, hours: int = 24):
    """Crée un JWT signé avec un jti unique, role et date d'expiration."""
    jti = str(uuid4())
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": jti,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    token = jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")
    return token, jti

def decode_token_or_401():
    token = _get_bearer_token()
    if not token:
        return None, (jsonify({"message": "Token manquant"}), 401)
    try:
        payload = jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "jti"]}
        )
    except jwt.ExpiredSignatureError:
        return None, (jsonify({"message": "Session expirée"}), 401)
    except jwt.InvalidTokenError:
        return None, (jsonify({"message": "Token invalide"}), 401)

    if payload.get("jti") in TOKEN_BLACKLIST:
        return None, (jsonify({"message": "Token révoqué"}), 401)

    return payload, None

def auth_required(roles: list[str] | None = None):
    """Décorateur à poser sur tes routes à protéger."""
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            payload, err = decode_token_or_401()
            if err:
                return err
            # expose l'utilisateur dans flask.g si tu veux
            g.jwt = payload
            if roles:
                if payload.get("role") not in roles:
                    return jsonify({"message": "Accès interdit"}), 403
            return fn(*args, **kwargs)
        return inner
    return wrapper
