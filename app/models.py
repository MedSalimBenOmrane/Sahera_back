from app.extensions import db
from datetime import date
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import validates


class Thematique(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    date_ouverture = db.Column(db.Date, nullable=True)
    date_cloture = db.Column(db.Date, nullable=True)
    sous_thematiques = db.relationship("SousThematique", backref="thematique", cascade="all, delete-orphan")


class SousThematique(db.Model):
    __tablename__ = "sousthematique"

    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(200), nullable=False)
    titre_en = db.Column(db.String(200), nullable=True)
    thematique_id = db.Column(db.Integer, db.ForeignKey("thematique.id"), nullable=False)

    questions = db.relationship("Question", backref="sous_thematique", cascade="all, delete-orphan")


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    texte = db.Column(db.Text, nullable=False)
    texte_en = db.Column(db.Text, nullable=True)
    sous_thematique_id = db.Column(db.Integer, db.ForeignKey("sousthematique.id"), nullable=False)

    # Type de champ: 'liste' | 'text' | 'date'
    type_champ = db.Column(db.String(20), nullable=False, default="liste")

    # Liste des choix pour le type 'liste'. Null/None pour autres types.
    options = db.Column(JSONB, nullable=True)
    options_en = db.Column(JSONB, nullable=True)

    reponses = db.relationship("Reponse", backref="question", cascade="all, delete-orphan")

    @validates("options", "options_en")
    def _validate_options(self, key, options):
        # Pour les questions de type 'liste', options doit être une liste non vide de chaînes uniques.
        # Pour 'text' ou 'date', options est ignoré et forcé à None.
        qtype = getattr(self, "type_champ", None)
        if qtype == "liste":
            if not isinstance(options, list) or len(options) == 0:
                raise ValueError("`options` doit être une liste non vide pour le type 'liste'.")
            cleaned, seen = [], set()
            for o in options:
                if not isinstance(o, str):
                    raise ValueError("Chaque option doit être une chaîne.")
                s = o.strip()
                if not s:
                    raise ValueError("Les options vides sont interdites.")
                if s in seen:
                    raise ValueError("Options en double interdites.")
                if len(s) > 255:
                    raise ValueError("Une option dépasse 255 caractères.")
                cleaned.append(s)
                seen.add(s)
            return cleaned
        else:
            return None


class Utilisateur(db.Model):
    __tablename__ = 'utilisateur'

    id = db.Column(db.Integer, primary_key=True)

    nom = db.Column(db.String(120), nullable=False)
    prenom = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    mot_de_passe = db.Column(db.String(255), nullable=False)
    date_naissance = db.Column(db.Date, nullable=True)
    ethnicite = db.Column(db.String(120), nullable=True)
    genre = db.Column(db.String(20), nullable=True)
    telephone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(50), nullable=False, default="utilisateur")
    type = db.Column(db.String(50))  # Pour le polymorphisme

    __mapper_args__ = {
        'polymorphic_identity': 'utilisateur',
        'polymorphic_on': type
    }

    reponses = db.relationship("Reponse", backref="utilisateur", cascade="all, delete-orphan")

    # Add this relationship for notification link table
    liaisons_notifications = db.relationship(
        "NotificationUtilisateur",
        back_populates="utilisateur",
        cascade="all, delete-orphan"
    )


class Admin(db.Model):
    """
    Simple Admin table with personal and authentication information.
    """
    __tablename__ = 'admin'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False)
    prenom = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    mot_de_passe = db.Column(db.String(255), nullable=False)
    date_naissance = db.Column(db.Date, nullable=True)
    telephone = db.Column(db.String(20), nullable=True)


class Reponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contenu = db.Column(db.String(255), nullable=False)
    date_creation = db.Column(db.Date, nullable=True)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey("utilisateur.id"), nullable=False)


class NotificationUtilisateur(db.Model):
    __tablename__ = 'notification_utilisateur'

    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'), primary_key=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey('utilisateur.id'), primary_key=True)
    est_lu = db.Column(db.Boolean, default=False)

    # Relations vers les entités Notification et Utilisateur
    notification = db.relationship("Notification", back_populates="liaisons_utilisateurs")
    utilisateur = db.relationship("Utilisateur", back_populates="liaisons_notifications")


class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(255), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    date_envoi = db.Column(db.DateTime, nullable=False, default=db.func.now())

    # Relationship with users via association table
    liaisons_utilisateurs = db.relationship(
        "NotificationUtilisateur",
        back_populates="notification",
        cascade="all, delete-orphan"
    )
