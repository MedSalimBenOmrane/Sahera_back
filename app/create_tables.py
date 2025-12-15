from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from app.extensions import db
from app.models import (Thematique, SousThematique, Question, Reponse,
                                 Utilisateur, Admin, Notification, NotificationUtilisateur)

# Direct DB credentials
DB_HOST = "saheraa.cvqwwmqiwnrd.eu-north-1.rds.amazonaws.com"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "saheraadmin"
DB_PASSWORD = "secret12345678"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    print("All tables created successfully!")
