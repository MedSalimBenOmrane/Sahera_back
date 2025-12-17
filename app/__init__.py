# app/__init__.py

from flask import Flask
from flask_cors import CORS
from app.extensions import db, migrate
from app.routes import api_bp
from dotenv import load_dotenv
import os

def create_app():
    """
    Create and configure the Flask application.
    """
    if os.getenv("FLASK_ENV") != "production":
        load_dotenv()  # Load environment variables from .env in non-prod

    app = Flask(__name__)

    # Enable CORS for all /api/* routes (explicit origins only)
    cors_origins = os.getenv("CORS_ORIGINS") or os.getenv("FRONTEND_BASE_URL") or "https://sahera-webapp.ca"
    allowed_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    # Prefer a full DATABASE_URL; fallback to individual pieces for local/dev
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        db_user = os.getenv("DB_USER")
        db_password = os.getenv("DB_PASSWORD")
        db_host = os.getenv("DB_HOST")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME")
        if not all([db_user, db_password, db_host, db_name]):
            raise RuntimeError("DATABASE_URL is not set and DB_USER/DB_PASSWORD/DB_HOST/DB_NAME are incomplete.")
        database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", app.config["SECRET_KEY"])
    
    # Initialize SQLAlchemy and migrations
    db.init_app(app)
    migrate.init_app(app, db)
    
    app.config.update(
        MAIL_SENDER_EMAIL=os.getenv("MAIL_SENDER_EMAIL", "no-reply@votre-app.local"),
        MAIL_SENDER_NAME=os.getenv("MAIL_SENDER_NAME", "Ma Plateforme"),
        SMTP_HOST=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        SMTP_PORT=int(os.getenv("SMTP_PORT", "587")),
        SMTP_USE_TLS=os.getenv("SMTP_USE_TLS", "true").lower() in ("1","true","yes","on"),
        SMTP_USERNAME=os.getenv("SMTP_USERNAME"),
        SMTP_PASSWORD=os.getenv("SMTP_PASSWORD"),
        FRONTEND_BASE_URL=os.getenv("FRONTEND_BASE_URL", "https://app.example.com"),
        SMTP_TIMEOUT=float(os.getenv("SMTP_TIMEOUT", "20")),
    )
    # Enregistre tes routes sur /api
    app.register_blueprint(api_bp, url_prefix="/api")

    return app
