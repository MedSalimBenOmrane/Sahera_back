"""
Extension module for initializing Flask extensions like SQLAlchemy and migrations.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()
