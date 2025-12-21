from flask import Blueprint, jsonify, request, abort
from werkzeug.exceptions import HTTPException
from app.models import Thematique, SousThematique, Question, Utilisateur, Admin, Reponse,Notification, NotificationUtilisateur
from app.extensions import db
from flask_bcrypt import Bcrypt
from flask_jwt_extended import create_access_token
from datetime import date
from sqlalchemy.orm import joinedload
from sqlalchemy import func 
import bcrypt
import jwt
from flask import current_app, request, jsonify, abort
import os
import io
import csv
import json
from sqlalchemy import  or_  
from sqlalchemy import func, case, and_
from sqlalchemy import JSON
from sqlalchemy.orm import validates
from datetime import datetime, timedelta, date as _date, time as _time
from app.utils import _serializer, _generate_otp, _hash, _check_hash
from itsdangerous import BadSignature, SignatureExpired


api_bp = Blueprint("api", __name__)

#pagination 
from math import ceil
from flask import request, abort, url_for
from sqlalchemy.orm.attributes import InstrumentedAttribute

MAX_PER_PAGE = 4

@api_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

def get_pagination_params(max_per_page: int | None = None):
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
    except ValueError:
        abort(400, description="page et per_page doivent être des entiers.")

    if page < 1 or per_page < 1:
        abort(400, description="page et per_page doivent être > 0.")

    cap = max_per_page if max_per_page is not None else MAX_PER_PAGE  # << clé
    if per_page > cap:
        per_page = cap
    return page, per_page

def apply_sorting(query, model, default="id"):
    raw = request.args.get("sort", default)  # ex: "name,-date_ouverture"
    orders = []
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        desc = part.startswith("-")
        field = part.lstrip("+-")
        col = getattr(model, field, None)
        if not isinstance(col, InstrumentedAttribute):
            abort(400, description=f"Champ de tri invalide: {field}")
        orders.append(col.desc() if desc else col.asc())
    return query.order_by(*orders)

def build_paginated_response(items, total, page, per_page):
    pages = max(ceil(total / per_page), 1) if per_page else 1  # <-- important
    base_args = dict(request.args)
    base_args.pop("page", None)
    base_args.pop("per_page", None)

    def make_url(p):
        return url_for(request.endpoint, page=p, per_page=per_page,
                       **(request.view_args or {}), **base_args, _external=True)

    return {
        "items": items,
        "meta": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
            "has_next": page < pages,
            "has_prev": page > 1,
            "next": make_url(page + 1) if page < pages else None,
            "prev": make_url(page - 1) if page > 1 else None,
        }
    }


def _get_lang():
    lang = (request.args.get("lang") or "fr").lower()
    return "en" if lang == "en" else "fr"


def _localize_value(value_fr, value_en, lang):
    if lang == "en":
        if value_en not in (None, ""):
            return value_en
        return value_fr
    if value_fr not in (None, ""):
        return value_fr
    return value_en


def _validate_option_alignment(options_fr, options_en, ctx=None):
    # Ignore alignment if one side is absent or empty
    if options_fr in (None, []) or options_en in (None, []):
        return
    if len(options_fr) != len(options_en):
        detail = f" (context: {ctx})" if ctx else ""
        abort(400, description=f"`options` et `options_en` doivent avoir la meme longueur pour aligner les traductions.{detail}")


def _normalize_type(raw):
    if raw is None:
        return ""
    value = str(raw).strip().lower()
    if not value:
        return ""
    value = value.replace(" ", "_").replace("-", "_")
    if value == "texte":
        return "text"
    return value


def _serialize_question(q, lang):
    options_localized = _localize_value(q.options, q.options_en, lang)
    return {
        "id": q.id,
        "texte": _localize_value(q.texte, q.texte_en, lang),
        "texte_fr": q.texte,
        "texte_en": q.texte_en,
        "sous_thematique_id": q.sous_thematique_id,
        "type": getattr(q, "type_champ", "liste"),
        "options": options_localized,
        "options_fr": q.options,
        "options_en": q.options_en
    }


def _serialize_sous_thematique(sous, lang, include_questions=False):
    data = {
        "id": sous.id,
        "titre": _localize_value(sous.titre, sous.titre_en, lang),
        "titre_fr": sous.titre,
        "titre_en": sous.titre_en,
        "thematique_id": sous.thematique_id
    }
    if include_questions:
        data["questions"] = [_serialize_question(q, lang) for q in sous.questions]
    return data


def _serialize_thematique(t, lang, include_sous=False):
    data = {
        "id": t.id,
        "name": _localize_value(t.name, t.name_en, lang),
        "name_fr": t.name,
        "name_en": t.name_en,
        "description": _localize_value(t.description, t.description_en, lang),
        "description_fr": t.description,
        "description_en": t.description_en,
        "date_ouverture": t.date_ouverture.isoformat() if t.date_ouverture else None,
        "date_cloture": t.date_cloture.isoformat() if t.date_cloture else None
    }
    if include_sous:
        data["sous_thematiques"] = [_serialize_sous_thematique(sous, lang, include_questions=True) for sous in t.sous_thematiques]
    return data


def _map_option_value(value, options_fr, options_en, target_lang):
    options_fr = options_fr or []
    options_en = options_en or []
    if target_lang == "en":
        if value in options_en:
            return value
        if value in options_fr:
            idx = options_fr.index(value)
            if idx < len(options_en) and options_en[idx] not in (None, ""):
                return options_en[idx]
        return value
    else:  # fr
        if value in options_fr:
            return value
        if value in options_en:
            idx = options_en.index(value)
            if idx < len(options_fr) and options_fr[idx] not in (None, ""):
                return options_fr[idx]
        return value


def _map_option_values(values, options_fr, options_en, target_lang):
    if not values:
        return []
    return [_map_option_value(v, options_fr, options_en, target_lang) for v in values]


def _parse_multi_contenu(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    if isinstance(raw, str):
        raw_str = raw.strip()
        if not raw_str:
            return []
        if raw_str.startswith("[") and raw_str.endswith("]"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if str(v).strip()]
            except Exception:
                pass
        if "||" in raw_str:
            return [s.strip() for s in raw_str.split("||") if s.strip()]
        if "/" in raw_str:
            return [s for s in _split_values(raw_str, "contenu") if s]
        return [raw_str]
    return []


def _serialize_reponse(r, lang):
    q = getattr(r, "question", None)
    qtype = getattr(q, "type_champ", "liste") if q else "liste"
    options_fr = getattr(q, "options", None) if q else None
    options_en = getattr(q, "options_en", None) if q else None

    contenu_fr = r.contenu
    contenu_en = r.contenu
    if q and qtype == "liste":
        contenu_fr = _map_option_value(r.contenu, options_fr, options_en, "fr")
        contenu_en = _map_option_value(r.contenu, options_fr, options_en, "en")
        contenu_localized = _map_option_value(r.contenu, options_fr, options_en, lang)
        contenu_raw = r.contenu
    elif q and qtype == "liste_multiple":
        raw_values = _parse_multi_contenu(r.contenu)
        contenu_fr = _map_option_values(raw_values, options_fr, options_en, "fr")
        contenu_en = _map_option_values(raw_values, options_fr, options_en, "en")
        contenu_localized = _map_option_values(raw_values, options_fr, options_en, lang)
        contenu_raw = raw_values
    else:
        contenu_localized = r.contenu
        contenu_raw = r.contenu

    return {
        "id": r.id,
        "contenu": contenu_localized,
        "contenu_raw": contenu_raw,
        "contenu_fr": contenu_fr,
        "contenu_en": contenu_en,
        "date_creation": r.date_creation.isoformat() if r.date_creation else None,
        "question_id": r.question_id,
        "utilisateur_id": r.utilisateur_id
    }
#Récupérer la liste de toutes les thématiques (avec leurs informations)
#Admin , User
@api_bp.route("/thematiques", methods=["GET"])
def get_thematiques():
    """
    Liste paginée des thématiques.
    Params: page, per_page, sort (ex: name,-date_ouverture), q (recherche)
    """
    page, per_page = get_pagination_params(max_per_page=1000)
    lang = _get_lang()

    q = Thematique.query

    # recherche simple sur name/description
    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(
            (Thematique.name.ilike(s)) |
            (Thematique.description.ilike(s)) |
            (Thematique.name_en.ilike(s)) |
            (Thematique.description_en.ilike(s))
        )

    # tri par défaut: plus récentes d'abord, puis nom
    q = apply_sorting(q, Thematique, default="-date_ouverture,name")

    total = q.order_by(None).with_entities(func.count(Thematique.id)).scalar()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [_serialize_thematique(t, lang) for t in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))
#Récupérer les thématiques ouvertes
@api_bp.route("/thematiques/ouvertes", methods=["GET"])
def get_thematiques_ouvertes():
    """
    Thématiques ouvertes (pas de date_cloture ou date_cloture future), paginées.
    Params: page, per_page, sort, q
    """
    page, per_page = get_pagination_params()
    lang = _get_lang()
    today = date.today()

    q = Thematique.query.filter(
        (Thematique.date_cloture == None) | (Thematique.date_cloture > today)
    )

    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(
            (Thematique.name.ilike(s)) |
            (Thematique.description.ilike(s)) |
            (Thematique.name_en.ilike(s)) |
            (Thematique.description_en.ilike(s))
        )

    q = apply_sorting(q, Thematique, default="-date_ouverture,name")

    total = q.order_by(None).with_entities(func.count(Thematique.id)).scalar()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [_serialize_thematique(t, lang) for t in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))
#Récupérer les thématiques fermees
@api_bp.route("/thematiques/fermees", methods=["GET"])
def get_thematiques_fermees():
    """
    Thématiques fermées (date_cloture <= aujourd'hui), paginées.
    Params: page, per_page, sort, q
    """
    page, per_page = get_pagination_params()
    lang = _get_lang()
    today = date.today()

    q = Thematique.query.filter(
        Thematique.date_cloture != None,
        Thematique.date_cloture <= today
    )

    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(
            (Thematique.name.ilike(s)) |
            (Thematique.description.ilike(s)) |
            (Thematique.name_en.ilike(s)) |
            (Thematique.description_en.ilike(s))
        )

    # ici un tri par défaut pertinent: plus récemment fermées d'abord, puis nom
    q = apply_sorting(q, Thematique, default="-date_cloture,name")

    total = q.order_by(None).with_entities(func.count(Thematique.id)).scalar()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [_serialize_thematique(t, lang) for t in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))
#Pour une thématique sélectionnée :
#Récupérer toutes les sous-thématiques associées
#Pour chaque sous-thématique : récupérer toutes les questions liées
#User,Admin
@api_bp.route("/thematiques/<int:thematique_id>/details", methods=["GET"])
def get_sous_thematiques_with_questions(thematique_id):
    thematique = Thematique.query.get_or_404(thematique_id)
    lang = _get_lang()
    return jsonify(_serialize_thematique(thematique, lang, include_sous=True))
#User,Admin
@api_bp.route("/thematiques/<int:id>", methods=["GET"])
def get_thematique(id):
    thematique = Thematique.query.get_or_404(id)
    lang = _get_lang()
    return jsonify(_serialize_thematique(thematique, lang))

#User,Admin
@api_bp.route("/thematiques/<string:name>", methods=["GET"])
def get_thematique_by_name(name):
    lang = _get_lang()
    thematique = Thematique.query.filter((Thematique.name == name) | (Thematique.name_en == name)).first()
    if not thematique:
        return jsonify({"message": "Thématique non trouvée"}), 404
    return jsonify(_serialize_thematique(thematique, lang))


#Ajouter une nouvelle thématique
#Admin
@api_bp.route("/thematiques", methods=["POST"])
def create_thematique():
    data = request.get_json()
    if not data or "name" not in data:
        abort(400, description="Missing 'name'")
    
    thematique = Thematique(
        name=data["name"],
        name_en=data.get("name_en"),
        description=data.get("description"),
        description_en=data.get("description_en"),
        date_ouverture=data.get("date_ouverture"),
        date_cloture=data.get("date_cloture")
    )
    db.session.add(thematique)
    db.session.commit()

    return jsonify(_serialize_thematique(thematique, _get_lang())), 201

#Admin
@api_bp.route("/thematiques/<int:id>", methods=["PUT"])
def update_thematique(id):
    thematique = Thematique.query.get_or_404(id)
    data = request.get_json()
    if not data or "name" not in data:
        abort(400, description="Missing 'name'")

    thematique.name = data["name"]
    thematique.name_en = data.get("name_en", thematique.name_en)
    thematique.description = data.get("description", thematique.description)
    thematique.description_en = data.get("description_en", thematique.description_en)
    thematique.date_ouverture = data.get("date_ouverture", thematique.date_ouverture)
    thematique.date_cloture = data.get("date_cloture", thematique.date_cloture)
    db.session.commit()

    return jsonify(_serialize_thematique(thematique, _get_lang()))
#Admin
#Supprimer une thématique existante
@api_bp.route("/thematiques/<int:id>", methods=["DELETE"])
def delete_thematique(id):
    """
    Delete a thematique by ID.
    Args:
        id (int): Thematique ID.
    Returns:
        JSON success message with 204 status.
    """
    thematique = Thematique.query.get_or_404(id)
    db.session.delete(thematique)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 204

#User, 
#Récupérer toutes les thématiques non complétées pour ce client  , un thematique completes , ca veut dire le client a repondu a toutes les questions de toutes les sous thematiques qui appartient a cce thematique
#Admin, User 

# crée thematique 
import io, csv
from flask import request, abort, jsonify
@api_bp.route("/thematiques/<int:thematique_id>/import_csv", methods=["POST"])
def import_sous_thematiques_questions(thematique_id):
    """
    CSV attendu avec entêtes:
      sous_thematique,question,options
    - options: liste separee par '/' (ex: Oui/Non/NSP)

    Chaque ligne:
      - crée la sous-thématique si nécessaire
      - crée la question avec ses options
    """
    thematique = Thematique.query.get_or_404(thematique_id)

    if 'file' not in request.files:
        abort(400, description="Missing CSV file")
    file = request.files['file']
    if file.filename == '':
        abort(400, description="No file selected")

    try:
        raw_bytes = file.stream.read()
        try:
            decoded = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = raw_bytes.decode("cp1252")
        lines = decoded.splitlines()
        if not lines:
            abort(400, description="CSV vide.")
        header_line = lines[0]
        delimiter = ","
        if ";" in header_line and "," not in header_line:
            delimiter = ";"
        elif "\t" in header_line and "," not in header_line and ";" not in header_line:
            delimiter = "\t"
        stream = io.StringIO(decoded)
        reader = csv.DictReader(stream, delimiter=delimiter)
        # Normaliser les entetes (BOM, espaces superflus)
        fieldnames = [(h or '').replace('\ufeff', '').strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = fieldnames
        headers = set(fieldnames)

        required_headers = {'sous_thematique', 'question', 'type', 'options'}
        optional_headers = {'sous_thematique_en', 'question_en', 'options_en'}
        if not required_headers.issubset(headers):
            abort(
                400,
                description=(
                    "Entetes CSV attendues au minimum: sous_thematique,question,type,options "
                    "(verifier le delimitateur , ; ou tab)."
                ),
            )
        unknown = headers - (required_headers | optional_headers)
        if unknown:
            abort(400, description=f"Entetes CSV inconnues: {', '.join(sorted(unknown))}")
    except Exception as e:
        abort(400, description=f"Cannot read CSV: {e}")

    created_subs = 0
    created_qs = 0

    cache_sous = {}  # pour éviter requêtes répétées

    for line_num, row in enumerate(reader, start=2):
        try:
            has_any = any(str(v).strip() for v in row.values() if v is not None)
            if not has_any:
                continue
            titre_sous = (row.get('sous_thematique') or '').strip()
            titre_sous_en = (row.get('sous_thematique_en') or '').strip()
            texte_q = (row.get('question') or '').strip()
            texte_q_en = (row.get('question_en') or '').strip()
            type_str = _normalize_type(row.get('type'))
            raw_opts = row.get('options')
            raw_opts_en = row.get('options_en')

            def _none_if_blank(val):
                if val is None:
                    return None
                if isinstance(val, str) and val.strip() == "":
                    return None
                return val

            if not titre_sous or not texte_q or not type_str:
                abort(400, description="Champs requis: sous_thematique, question, type")

            if type_str not in ("liste", "liste_multiple", "text", "date"):
                abort(400, description="Type non supporte (liste, liste_multiple, text, date).")

            options = None
            options_en = None
            if type_str in ("liste", "liste_multiple"):
                options = _normalize_options(raw_opts)
                raw_opts_en = _none_if_blank(raw_opts_en)
                if raw_opts_en is not None:
                    options_en = _normalize_options(raw_opts_en)
                _validate_option_alignment(options, options_en, ctx=texte_q)
        except HTTPException as exc:
            abort(exc.code or 400, description=f"Ligne {line_num}: {exc.description}")
        except Exception as exc:
            abort(400, description=f"Ligne {line_num}: {exc}")

        key = (thematique.id, titre_sous)
        sous = cache_sous.get(key)
        if not sous:
            sous = SousThematique.query.filter_by(thematique_id=thematique.id, titre=titre_sous).first()
            if not sous:
                sous = SousThematique(titre=titre_sous, titre_en=titre_sous_en or None, thematique_id=thematique.id)
                db.session.add(sous)
                db.session.flush()
                created_subs += 1
            elif titre_sous_en and not sous.titre_en:
                sous.titre_en = titre_sous_en
            cache_sous[key] = sous

        question = Question(
            texte=texte_q,
            texte_en=texte_q_en or None,
            sous_thematique_id=sous.id,
            type_champ=type_str,
            options=options,
            options_en=options_en
        )
        db.session.add(question)
        created_qs += 1

    db.session.commit()
    return jsonify({"created_sous_thematiques": created_subs, "created_questions": created_qs}), 200

@api_bp.route("/thematiques/non-completes/<int:utilisateur_id>", methods=["GET"])
def get_incomplete_thematiques(utilisateur_id):
    """
    Thématiques non complétées par un client.
    - Complète = l'utilisateur a répondu à TOUTES les questions de TOUTES les sous-thématiques.
    - Ici on renvoie celles avec 0 question OU avec nb_réponses < nb_questions.
    Params: page, per_page, sort (ex: name,-id), q (recherche sur name/description)
    """
    page, per_page = get_pagination_params(max_per_page=1000)
    lang = _get_lang()

    # Sous-requête: nombre total de questions par thématique
    questions_sq = (
        db.session.query(
            Thematique.id.label("thematique_id"),
            func.count(Question.id).label("nb_questions")
        )
        .outerjoin(SousThematique, SousThematique.thematique_id == Thematique.id)
        .outerjoin(Question, Question.sous_thematique_id == SousThematique.id)
        .group_by(Thematique.id)
        .subquery()
    )

    # Sous-requête: nombre de réponses de CE user par thématique
    reponses_sq = (
        db.session.query(
            Thematique.id.label("thematique_id"),
            func.count(Reponse.id).label("nb_reponses")
        )
        .outerjoin(SousThematique, SousThematique.thematique_id == Thematique.id)
        .outerjoin(Question, Question.sous_thematique_id == SousThematique.id)
        .outerjoin(
            Reponse,
            and_(
                Reponse.question_id == Question.id,
                Reponse.utilisateur_id == utilisateur_id
            )
        )
        .group_by(Thematique.id)
        .subquery()
    )

    nbq = func.coalesce(questions_sq.c.nb_questions, 0)
    nbr = func.coalesce(reponses_sq.c.nb_reponses, 0)

    q = (
        db.session.query(Thematique.id, Thematique.name, Thematique.name_en)
        .outerjoin(questions_sq, questions_sq.c.thematique_id == Thematique.id)
        .outerjoin(reponses_sq, reponses_sq.c.thematique_id == Thematique.id)
        .filter(or_(nbq == 0, nbr < nbq))
    )

    # Recherche
    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Thematique.name.ilike(s),
                         Thematique.description.ilike(s),
                         Thematique.name_en.ilike(s),
                         Thematique.description_en.ilike(s)))

    # Tri (par défaut par name)
    q = apply_sorting(q, Thematique, default="name")

    # Total + page
    total = q.order_by(None).with_entities(func.count()).scalar()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [{"id": rid, "name": _localize_value(rname, rname_en, lang), "name_fr": rname, "name_en": rname_en} for (rid, rname, rname_en) in rows]
    return jsonify(build_paginated_response(items, total, page, per_page))

#Admin, user
#Récupérer toutes les thématiques complétées pour ce client  , un thematique completes , ca veut dire le client a repondu a toutes les questions de toutes les sous thematiques qui appartient a cce thematique
@api_bp.route("/thematiques/completes/<int:utilisateur_id>", methods=["GET"])
def get_completed_thematiques(utilisateur_id):
    """
    Thématiques complétées par un client (nb_reponses == nb_questions ET nb_questions > 0).
    Params: page, per_page, sort, q
    """
    page, per_page = get_pagination_params(max_per_page=1000) 
    lang = _get_lang()

    questions_sq = (
        db.session.query(
            Thematique.id.label("thematique_id"),
            func.count(Question.id).label("nb_questions")
        )
        .outerjoin(SousThematique, SousThematique.thematique_id == Thematique.id)
        .outerjoin(Question, Question.sous_thematique_id == SousThematique.id)
        .group_by(Thematique.id)
        .subquery()
    )

    reponses_sq = (
        db.session.query(
            Thematique.id.label("thematique_id"),
            func.count(Reponse.id).label("nb_reponses")
        )
        .outerjoin(SousThematique, SousThematique.thematique_id == Thematique.id)
        .outerjoin(Question, Question.sous_thematique_id == SousThematique.id)
        .outerjoin(
            Reponse,
            and_(
                Reponse.question_id == Question.id,
                Reponse.utilisateur_id == utilisateur_id
            )
        )
        .group_by(Thematique.id)
        .subquery()
    )

    nbq = func.coalesce(questions_sq.c.nb_questions, 0)
    nbr = func.coalesce(reponses_sq.c.nb_reponses, 0)

    q = (
        db.session.query(Thematique.id, Thematique.name, Thematique.name_en)
        .outerjoin(questions_sq, questions_sq.c.thematique_id == Thematique.id)
        .outerjoin(reponses_sq, reponses_sq.c.thematique_id == Thematique.id)
        .filter(and_(nbq > 0, nbr == nbq))
    )

    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Thematique.name.ilike(s),
                         Thematique.description.ilike(s),
                         Thematique.name_en.ilike(s),
                         Thematique.description_en.ilike(s)))

    q = apply_sorting(q, Thematique, default="name")

    total = q.order_by(None).with_entities(func.count()).scalar()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [{"id": rid, "name": _localize_value(rname, rname_en, lang), "name_fr": rname, "name_en": rname_en} for (rid, rname, rname_en) in rows]
    return jsonify(build_paginated_response(items, total, page, per_page))
# SousThematique routes
##User,Admin
@api_bp.route("/thematiques/<int:thematique_id>/sousthematiques", methods=["GET"])
def get_sousthematiques(thematique_id):
    """
    Get all sous-thematiques under a specific thematique.
    """
    thematique = Thematique.query.get_or_404(thematique_id)
    lang = _get_lang()
    sous_thematiques = SousThematique.query.filter_by(thematique_id=thematique.id).all()
    return jsonify([_serialize_sous_thematique(s, lang) for s in sous_thematiques])
#User,Admin
@api_bp.route("/thematiques/<int:thematique_id>/sousthematiques/<int:id>", methods=["GET"])
def get_sousthematique(thematique_id, id):
    """
    Get a specific sous-thematique under a thematique.
    """
    sous_thematique = SousThematique.query.filter_by(id=id, thematique_id=thematique_id).first_or_404()
    lang = _get_lang()
    return jsonify(_serialize_sous_thematique(sous_thematique, lang))
#Admin
@api_bp.route("/thematiques/<int:thematique_id>/sousthematiques", methods=["POST"])
def create_sousthematique(thematique_id):
    """
    Create a new sous-thematique under a given thematique.
    """
    thematique = Thematique.query.get_or_404(thematique_id)
    data = request.get_json()
    if not data or "titre" not in data:
        abort(400, description="Missing 'titre'")
    lang = _get_lang()

    sous_thematique = SousThematique(
        titre=data["titre"],
        titre_en=data.get("titre_en"),
        thematique_id=thematique.id
    )
    db.session.add(sous_thematique)
    db.session.commit()
    return jsonify(_serialize_sous_thematique(sous_thematique, lang)), 201
#Admin
@api_bp.route("/thematiques/<int:thematique_id>/sousthematiques/<int:id>", methods=["PUT"])
def update_sousthematique(thematique_id, id):
    """
    Update a sous-thematique that belongs to a specific thematique.
    """
    sous_thematique = SousThematique.query.filter_by(id=id, thematique_id=thematique_id).first_or_404()
    data = request.get_json()
    if not data or "titre" not in data:
        abort(400, description="Missing 'titre'")
    lang = _get_lang()

    sous_thematique.titre = data["titre"]
    sous_thematique.titre_en = data.get("titre_en", sous_thematique.titre_en)
    db.session.commit()
    return jsonify(_serialize_sous_thematique(sous_thematique, lang))
#Admin
@api_bp.route("/thematiques/<int:thematique_id>/sousthematiques/<int:id>", methods=["DELETE"])
def delete_sousthematique(thematique_id, id):
    """
    Delete a sous-thematique that belongs to a specific thematique.
    """
    sous_thematique = SousThematique.query.filter_by(id=id, thematique_id=thematique_id).first_or_404()
    db.session.delete(sous_thematique)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 204

# Question routes
#helpers 
# Helpers pour normaliser et valider les options
def _split_values(raw, field_name):
    if isinstance(raw, str):
        if "/" in raw:
            items = []
            buf = []
            i = 0
            while i < len(raw):
                ch = raw[i]
                if ch == "\\" and i + 1 < len(raw) and raw[i + 1] == "/":
                    buf.append("/")
                    i += 2
                    continue
                if ch == "/":
                    items.append("".join(buf).strip())
                    buf = []
                    i += 1
                    continue
                buf.append(ch)
                i += 1
            items.append("".join(buf).strip())
            return items
        return [raw.strip()]
    if isinstance(raw, list):
        return [str(s).strip() for s in raw]
    abort(400, description=f"`{field_name}` doit etre une liste de chaines ou une chaine separee par / (utiliser \\/ pour un / literal)")


def _normalize_multi_values(raw):
    if raw is None:
        abort(400, description="`contenu` est requis.")

    items = None
    if isinstance(raw, str):
        raw_str = raw.strip()
        if raw_str.startswith("[") and raw_str.endswith("]"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    items = [str(s).strip() for s in parsed]
            except Exception:
                items = None
        if items is None:
            items = _split_values(raw_str, "contenu")
    else:
        items = _split_values(raw, "contenu")

    seen, cleaned = set(), []
    for s in items:
        if not s:
            continue
        if len(s) > 255:
            abort(400, description="Une valeur depasse 255 caracteres.")
        if s not in seen:
            cleaned.append(s)
            seen.add(s)

    if not cleaned:
        abort(400, description="`contenu` ne peut pas etre vide.")
    return cleaned


def _serialize_multi_values(values):
    return json.dumps(values, ensure_ascii=False)


def _normalize_options(raw):
    """
    Accepte:
      - liste de chaines
      - chaine unique avec separateur '/' -> ex: "Oui/Non/NSP"
    Retourne une liste de chaines nettoyees, uniques, ordre conserve.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        items = _split_values(raw, "options")
    elif isinstance(raw, list):
        items = _split_values(raw, "options")
    else:
        abort(400, description="`options` doit etre une liste de chaines ou une chaine separee par / (utiliser \\/ pour un / literal)")

    # filtre vides + unicité
    seen, cleaned = set(), []
    for s in items:
        if not s:
            continue
        if len(s) > 255:
            abort(400, description="Une option dépasse 255 caractères.")
        if s not in seen:
            cleaned.append(s)
            seen.add(s)

    if not cleaned:
        abort(400, description="`options` ne peut pas être vide.")
    return cleaned


def _assert_value_in_options(contenu, options, options_en=None):
    if contenu is None or contenu.strip() == "":
        abort(400, description="`contenu` est requis.")
    available = set(options or [])
    if options_en:
        available.update(options_en)
    if contenu not in available:
        abort(400, description="La réponse doit être l'une des options disponibles.")


def _assert_values_in_options(values, options, options_en=None):
    if not values:
        abort(400, description="`contenu` est requis.")
    available = set(options or [])
    if options_en:
        available.update(options_en)
    missing = [v for v in values if v not in available]
    if missing:
        abort(400, description="La reponse doit etre l'une des options disponibles.")
#Admin,User

@api_bp.route("/questions", methods=["GET"])
def get_questions():
    """
    Liste paginée des questions.
    Params:
      - page, per_page
      - q: recherche (texte)
      - sous_thematique_id
      - sort: ex "id" ou "-id" (par défaut "id")
    """
    page, per_page = get_pagination_params()
    lang = _get_lang()

    q = Question.query

    stid = request.args.get("sous_thematique_id")
    if stid is not None:
        try:
            q = q.filter(Question.sous_thematique_id == int(stid))
        except ValueError:
            abort(400, description="`sous_thematique_id` doit être un entier.")

    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Question.texte.ilike(s), Question.texte_en.ilike(s)))

    q = apply_sorting(q, Question, default="id")

    total = q.order_by(None).with_entities(func.count(Question.id)).scalar()
    rows  = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [_serialize_question(q_, lang) for q_ in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))
#Admin,User
@api_bp.route("/questions/<int:id>", methods=["GET"])
def get_question(id):
    """
    Get a single question by ID.
    Args:
        id (int): Question ID.
    Returns:
        JSON of the question data or 404 if not found.
    """
    question = Question.query.get_or_404(id)
    lang = _get_lang()
    return jsonify(_serialize_question(question, lang))
#Admin
@api_bp.route("/questions", methods=["POST"])
def create_question():
    """
    Request JSON:
      {
        "texte": "Question text",
        "sous_thematique_id": 1,
        "options": ["Oui", "Non", "NSP"]  # ou "Oui|Non|NSP"
      }
    """
    data = request.get_json() or {}
    lang = _get_lang()
    if "texte" not in data or "sous_thematique_id" not in data:
        abort(400, description="Champs requis: texte, sous_thematique_id")

    type_str = _normalize_type(data.get("type")) or "liste"
    if type_str not in ("liste", "liste_multiple", "text", "date"):
        abort(400, description="type invalide: doit etre 'liste', 'liste_multiple', 'text' ou 'date'")

    options = None
    options_en = None
    if type_str in ("liste", "liste_multiple"):
        if "options" not in data:
            abort(400, description="`options` est requis pour le type 'liste' ou 'liste_multiple'")
        options = _normalize_options(data["options"])
        if "options_en" in data:
            options_en = _normalize_options(data["options_en"])
        _validate_option_alignment(options, options_en)
    else:
        options_en = None

    q = Question(
        texte=data["texte"],
        texte_en=data.get("texte_en"),
        sous_thematique_id=data["sous_thematique_id"],
        type_champ=type_str,
        options=options,
        options_en=options_en
    )
    db.session.add(q)
    db.session.commit()
    return jsonify(_serialize_question(q, lang)), 201
#Admin
@api_bp.route("/questions/<int:id>", methods=["PUT"])
def update_question(id):
    """
    Request JSON (au moins un champ):
      {
        "texte": "nouveau libellé",
        "sous_thematique_id": 2,
        "options": ["A","B","C"]  # ou "A|B|C"
      }
    Règle: si des réponses existent et qu'on modifie `options`,
           toutes les valeurs déjà répondues doivent exister dans les nouvelles options.
    """
    q = Question.query.get_or_404(id)
    data = request.get_json() or {}
    lang = _get_lang()

    prev_type = getattr(q, "type_champ", "liste")
    new_type = prev_type

    if "texte" in data:
        q.texte = data["texte"]
    if "texte_en" in data:
        q.texte_en = data["texte_en"]

    if "sous_thematique_id" in data:
        q.sous_thematique_id = data["sous_thematique_id"]

    if "type" in data:
        tmp_type = _normalize_type(data.get("type"))
        if not tmp_type or tmp_type not in ("liste", "liste_multiple", "text", "date"):
            abort(400, description="type invalide: doit etre 'liste', 'liste_multiple', 'text' ou 'date'")
        new_type = tmp_type

    new_options = q.options
    new_options_en = q.options_en

    if "options" in data:
        new_options = _normalize_options(data["options"])
    if "options_en" in data:
        new_options_en = _normalize_options(data["options_en"])

    if new_type in ("liste", "liste_multiple"):
        if new_options is None:
            abort(400, description="`options` est requis pour le type 'liste' ou 'liste_multiple'")
        _validate_option_alignment(new_options, new_options_en)
        used_rows = db.session.query(Reponse.contenu).filter(Reponse.question_id == q.id).distinct().all()
        used_values = set()
        if prev_type == "liste_multiple":
            for (val,) in used_rows:
                for item in _parse_multi_contenu(val):
                    used_values.add(item)
        else:
            used_values = {val for (val,) in used_rows}
        available = set(new_options or [])
        if new_options_en:
            available.update(new_options_en)
        missing = [v for v in used_values if v not in available]
        if missing:
            abort(409, description=f"Impossible de retirer des options déjà utilisées: {missing}")
    else:
        new_options = None
        new_options_en = None

    q.type_champ = new_type
    q.options = new_options
    q.options_en = new_options_en

    db.session.commit()
    return jsonify(_serialize_question(q, lang))
#Admin
@api_bp.route("/questions/<int:id>", methods=["DELETE"])
def delete_question(id):
    """
    Delete a question by ID.
    Args:
        id (int): Question ID.
    Returns:
        JSON success message with 204 status.
    """
    question = Question.query.get_or_404(id)
    db.session.delete(question)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 204


#Récupérer la liste de tous les utilisateurs (clients) et leurs informations de base
# Get all users
# Récupérer la liste de tous les utilisateurs (clients) et leurs informations de base
#Admin
@api_bp.route("/utilisateurs", methods=["GET"])
def get_utilisateurs():
    """
    Liste paginée des utilisateurs.
    Params:
      - page, per_page
      - q: recherche (nom/prenom/email)
      - sort: ex "nom,prenom" ou "-date_naissance,nom"
    """
    page, per_page = get_pagination_params()

    q = Utilisateur.query
    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Utilisateur.nom.ilike(s),
                         Utilisateur.prenom.ilike(s),
                         Utilisateur.email.ilike(s)))

    q = apply_sorting(q, Utilisateur, default="nom,prenom")

    total = q.order_by(None).with_entities(func.count(Utilisateur.id)).scalar()
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [{
        "id": u.id,
        "nom": u.nom,
        "prenom": u.prenom,
        "email": u.email,
        "telephone": u.telephone,
        "date_naissance": u.date_naissance.isoformat() if u.date_naissance else None,
        "ethnicite": u.ethnicite,
        "genre": u.genre,
        "role": u.role
    } for u in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))

#Admin
# Récupérer un seul utilisateur par ID
@api_bp.route("/utilisateurs/<int:id>", methods=["GET"])
def get_utilisateur(id):
    u = Utilisateur.query.get_or_404(id)
    return jsonify({
        "id": u.id,
        "nom": u.nom,
        "prenom": u.prenom,
        "email": u.email,
        "telephone": u.telephone,
        "date_naissance": u.date_naissance.isoformat() if u.date_naissance else None,
        "ethnicite": u.ethnicite,
        "genre": u.genre,
        "role": u.role
    })

#Admin, User
# Créer un nouvel utilisateur
@api_bp.route("/utilisateurs", methods=["POST"])
def create_utilisateur():
    data = request.get_json()
    required_fields = ["nom", "prenom", "email", "mot_de_passe"]
    if not all(field in data for field in required_fields):
        abort(400, description="Champs requis manquants")

    hashed_password = bcrypt.hashpw(data["mot_de_passe"].encode('utf-8'), bcrypt.gensalt())

    u = Utilisateur(
        nom=data["nom"],
        prenom=data["prenom"],
        email=data["email"],
        mot_de_passe=hashed_password.decode('utf-8'),
        date_naissance=data.get("date_naissance"),
        ethnicite=data.get("ethnicite"),
        genre=data.get("genre"),
        telephone=data.get("telephone"),
        role=data.get("role", "utilisateur")
    )
    db.session.add(u)
    db.session.commit()
    return jsonify({"id": u.id}), 201


#Admin, User
# Mettre à jour un utilisateur existant
@api_bp.route("/utilisateurs/<int:id>", methods=["PUT"])
def update_utilisateur(id):
    u = Utilisateur.query.get_or_404(id)
    data = request.get_json()

    u.nom = data.get("nom", u.nom)
    u.prenom = data.get("prenom", u.prenom)
    u.email = data.get("email", u.email)

    # Hash the password only if a new one is provided
    if "mot_de_passe" in data and data["mot_de_passe"]:
        hashed_password = bcrypt.hashpw(data["mot_de_passe"].encode('utf-8'), bcrypt.gensalt())
        u.mot_de_passe = hashed_password.decode('utf-8')

    u.date_naissance = data.get("date_naissance", u.date_naissance)
    u.ethnicite = data.get("ethnicite", u.ethnicite)
    u.genre = data.get("genre", u.genre)
    u.telephone = data.get("telephone", u.telephone)
    u.role = data.get("role", u.role)

    db.session.commit()
    return jsonify({
        "message": "Utilisateur mis à jour avec succès",
        "id": u.id,
        "nom": u.nom,
        "prenom": u.prenom,
        "email": u.email,
        "telephone": u.telephone
    }), 200

#Admin
# Supprimer un utilisateur
@api_bp.route("/utilisateurs/<int:id>", methods=["DELETE"])
def delete_utilisateur(id):
    u = Utilisateur.query.get_or_404(id)
    db.session.delete(u)
    db.session.commit()
    return jsonify({"message": "Utilisateur supprimé"}), 204

#admin
# Get all admins
@api_bp.route("/admins", methods=["GET"])
def get_admins():
    admins = Admin.query.all()
    return jsonify([
        {
            "id": a.id,
            "nom": a.nom,
            "prenom": a.prenom,
            "email": a.email,
            "date_naissance": a.date_naissance.isoformat() if a.date_naissance else None,
            "telephone": a.telephone,
            "mail_sender_email": a.mail_sender_email,
            "mail_sender_name": a.mail_sender_name,
            "smtp_host": a.smtp_host,
            "smtp_port": a.smtp_port,
            "smtp_use_tls": a.smtp_use_tls,
            "smtp_username": a.smtp_username,
            "smtp_password": a.smtp_password,
        } for a in admins
    ])

# GET a specific admin
@api_bp.route("/admins/<int:id>", methods=["GET"])
def get_admin(id):
    a = Admin.query.get_or_404(id)
    return jsonify({
        "id": a.id,
        "nom": a.nom,
        "prenom": a.prenom,
        "email": a.email,
        "date_naissance": a.date_naissance.isoformat() if a.date_naissance else None,
        "telephone": a.telephone,
        "mail_sender_email": a.mail_sender_email,
        "mail_sender_name": a.mail_sender_name,
        "smtp_host": a.smtp_host,
        "smtp_port": a.smtp_port,
        "smtp_use_tls": a.smtp_use_tls,
        "smtp_username": a.smtp_username,
        "smtp_password": a.smtp_password,
    })

# POST create a new admin
@api_bp.route("/admins", methods=["POST"])
def create_admin():
    data = request.get_json()
    mot_de_passe_en_clair = data.get("mot_de_passe")

    if not mot_de_passe_en_clair:
        return jsonify({"error": "Mot de passe est requis"}), 400

    mot_de_passe_hash = bcrypt.hashpw(
        mot_de_passe_en_clair.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    admin = Admin(
        nom=data.get("nom"),
        prenom=data.get("prenom"),
        email=data.get("email"),
        mot_de_passe=mot_de_passe_hash,
        date_naissance=data.get("date_naissance"),
        telephone=data.get("telephone")
    )
    db.session.add(admin)
    db.session.commit()
    return jsonify({"id": admin.id}), 201

# PUT update an existing admin
@api_bp.route("/admins/<int:id>", methods=["PUT"])
def update_admin(id):
    admin = Admin.query.get_or_404(id)
    data = request.get_json()

    admin.nom = data.get("nom", admin.nom)
    admin.prenom = data.get("prenom", admin.prenom)
    admin.email = data.get("email", admin.email)
    admin.date_naissance = data.get("date_naissance", admin.date_naissance)
    admin.telephone = data.get("telephone", admin.telephone)
    admin.mail_sender_email = data.get("mail_sender_email", admin.mail_sender_email)
    admin.mail_sender_name = data.get("mail_sender_name", admin.mail_sender_name)
    admin.smtp_host = data.get("smtp_host", admin.smtp_host)
    admin.smtp_port = data.get("smtp_port", admin.smtp_port)
    if "smtp_use_tls" in data:
        admin.smtp_use_tls = bool(data.get("smtp_use_tls"))
    admin.smtp_username = data.get("smtp_username", admin.smtp_username)
    admin.smtp_password = data.get("smtp_password", admin.smtp_password)

    nouveau_mot_de_passe = data.get("mot_de_passe")
    if nouveau_mot_de_passe:
        admin.mot_de_passe = bcrypt.hashpw(
            nouveau_mot_de_passe.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

    db.session.commit()
    return jsonify({"id": admin.id})

# DELETE an admin
@api_bp.route("/admins/<int:id>", methods=["DELETE"])
def delete_admin(id):
    admin = Admin.query.get_or_404(id)
    db.session.delete(admin)
    db.session.commit()
    return jsonify({"message": "Admin supprimé"}), 204

# Obtenir toutes les réponses
#Admin, User

@api_bp.route("/reponses", methods=["GET"])
def get_reponses():
    """
    Liste des réponses (non paginée).
    Filtres optionnels:
      - question_id
      - utilisateur_id
      - date_from (YYYY-MM-DD)
      - date_to   (YYYY-MM-DD)
    """
    lang = _get_lang()
    q = Reponse.query

    # filtres
    qid = request.args.get("question_id", type=int)
    if qid is not None:
        q = q.filter(Reponse.question_id == qid)

    uid = request.args.get("utilisateur_id", type=int)
    if uid is not None:
        q = q.filter(Reponse.utilisateur_id == uid)

    dfrom = request.args.get("date_from")
    if dfrom:
        try:
            q = q.filter(Reponse.date_creation >= _date.fromisoformat(dfrom))
        except ValueError:
            abort(400, description="`date_from` doit être au format YYYY-MM-DD.")

    dto = request.args.get("date_to")
    if dto:
        try:
            q = q.filter(Reponse.date_creation <= _date.fromisoformat(dto))
        except ValueError:
            abort(400, description="`date_to` doit être au format YYYY-MM-DD.")

    rows = q.order_by(Reponse.date_creation.desc(), Reponse.id.asc()).all()

    return jsonify([_serialize_reponse(r, lang) for r in rows])
#Admin, User
# Obtenir une réponse par ID
@api_bp.route("/reponses/<int:id>", methods=["GET"])
def get_reponse(id):
    r = Reponse.query.get_or_404(id)
    lang = _get_lang()
    return jsonify(_serialize_reponse(r, lang))
#User
# Créer une nouvelle réponse
@api_bp.route("/reponses", methods=["POST"])
def create_reponse():
    data = request.get_json() or {}
    required = ["contenu", "question_id", "utilisateur_id"]
    if not all(k in data for k in required):
        abort(400, description="Champs requis manquants : contenu, question_id, utilisateur_id")

    # date_creation
    if "date_creation" in data:
        try:
            date_creation = datetime.fromisoformat(data["date_creation"]).date()
        except ValueError:
            abort(400, description="Format de date_creation invalide, attendu YYYY-MM-DD")
    else:
        date_creation = date.today()

    q = Question.query.get_or_404(data["question_id"])
    qtype = getattr(q, "type_champ", "liste")
    contenu_value = data["contenu"]
    response_contenu = contenu_value
    if qtype in ("liste", "liste_multiple"):
        if (not q.options or not isinstance(q.options, list)) and (not q.options_en or not isinstance(q.options_en, list)):
            abort(400, description="La question n'a pas d'options definies.")
        if qtype == "liste":
            _assert_value_in_options(contenu_value, q.options, q.options_en)
        else:
            values = _normalize_multi_values(contenu_value)
            _assert_values_in_options(values, q.options, q.options_en)
            contenu_value = _serialize_multi_values(values)
            response_contenu = values
    elif qtype == "text":
        if (contenu_value or "").strip() == "":
            abort(400, description="Le contenu ne peut pas etre vide.")
    elif qtype == "date":
        try:
            _date.fromisoformat(contenu_value)
        except Exception:
            abort(400, description="Le contenu doit etre une date au format YYYY-MM-DD.")

    r = Reponse(
        contenu=contenu_value,
        date_creation=date_creation,
        question_id=q.id,
        utilisateur_id=data["utilisateur_id"]
    )
    db.session.add(r)
    db.session.commit()

    return jsonify({
        "id": r.id,
        "contenu": response_contenu,
        "date_creation": r.date_creation.isoformat(),
        "question_id": r.question_id,
        "utilisateur_id": r.utilisateur_id
    }), 201
#User
# Mettre à jour une réponse existante
@api_bp.route("/reponses/<int:id>", methods=["PUT"])
def update_reponse(id):
    r = Reponse.query.get_or_404(id)
    data = request.get_json() or {}

    if "contenu" in data:
        q = Question.query.get_or_404(data.get("question_id", r.question_id))
        qtype = getattr(q, "type_champ", "liste")
        contenu_value = data["contenu"]
        if qtype in ("liste", "liste_multiple"):
            if (not q.options or not isinstance(q.options, list)) and (not q.options_en or not isinstance(q.options_en, list)):
                abort(400, description="La question n'a pas d'options definies.")
            if qtype == "liste":
                _assert_value_in_options(contenu_value, q.options, q.options_en)
                r.contenu = contenu_value
            else:
                values = _normalize_multi_values(contenu_value)
                _assert_values_in_options(values, q.options, q.options_en)
                r.contenu = _serialize_multi_values(values)
        elif qtype == "text":
            if (contenu_value or "").strip() == "":
                abort(400, description="Le contenu ne peut pas etre vide.")
            r.contenu = contenu_value
        elif qtype == "date":
            try:
                _date.fromisoformat(contenu_value)
            except Exception:
                abort(400, description="Le contenu doit etre une date au format YYYY-MM-DD.")
            r.contenu = contenu_value

    if "date_creation" in data:
        try:
            r.date_creation = datetime.fromisoformat(data["date_creation"]).date()
        except ValueError:
            abort(400, description="Format de date_creation invalide, attendu YYYY-MM-DD")

    if "question_id" in data:
        # si on change de question, revalider la coherence contenu/options
        new_q = Question.query.get_or_404(data["question_id"])
        new_type = getattr(new_q, "type_champ", "liste")
        if new_type in ("liste", "liste_multiple"):
            if (not new_q.options or not isinstance(new_q.options, list)) and (not new_q.options_en or not isinstance(new_q.options_en, list)):
                abort(400, description="La question n'a pas d'options definies.")
            if "contenu" in data:
                if new_type == "liste":
                    _assert_value_in_options(data["contenu"], new_q.options, new_q.options_en)
                else:
                    values = _normalize_multi_values(data["contenu"])
                    _assert_values_in_options(values, new_q.options, new_q.options_en)
            else:
                if new_type == "liste":
                    _assert_value_in_options(r.contenu, new_q.options, new_q.options_en)
                else:
                    values = _parse_multi_contenu(r.contenu)
                    _assert_values_in_options(values, new_q.options, new_q.options_en)
        else:
            value = data.get("contenu", r.contenu)
            if new_type == "text":
                if (value or "").strip() == "":
                    abort(400, description="Le contenu ne peut pas etre vide.")
            elif new_type == "date":
                try:
                    _date.fromisoformat(value)
                except Exception:
                    abort(400, description="Le contenu doit etre une date au format YYYY-MM-DD.")
        r.question_id = new_q.id

    r.utilisateur_id = data.get("utilisateur_id", r.utilisateur_id)

    db.session.commit()
    response_q = r.question
    response_type = getattr(response_q, "type_champ", "liste") if response_q else "liste"
    if response_type == "liste_multiple":
        response_contenu = _parse_multi_contenu(r.contenu)
    else:
        response_contenu = r.contenu
    return jsonify({
        "id": r.id,
        "contenu": response_contenu,
        "date_creation": r.date_creation.isoformat() if r.date_creation else None,
        "question_id": r.question_id,
        "utilisateur_id": r.utilisateur_id
    })
#User
# Supprimer une réponse
@api_bp.route("/reponses/<int:id>", methods=["DELETE"])
def delete_reponse(id):
    r = Reponse.query.get_or_404(id)
    db.session.delete(r)
    db.session.commit()
    return jsonify({"message": "Réponse supprimée"}), 204
#User, Admin
# Récupérer les réponses d’un client pour une sous-thématique
@api_bp.route("/clients/<int:utilisateur_id>/sousthematiques/<int:sous_id>/reponses", methods=["GET"])
def get_reponses_client_sousthematique(utilisateur_id, sous_id):
    questions = Question.query.filter_by(sous_thematique_id=sous_id).all()
    question_ids = [q.id for q in questions]
    reponses = Reponse.query.filter(
        Reponse.utilisateur_id == utilisateur_id,
        Reponse.question_id.in_(question_ids)
    ).all()
    lang = _get_lang()

    response_data = [_serialize_reponse(rep, lang) for rep in reponses]
    return jsonify(response_data)
#User, Admin
#Récupérer toutes les questions (pour la sous-thématique sélectionnée)
@api_bp.route("/sousthematiques/<int:sous_id>/questions", methods=["GET"])
def get_questions_by_sousthematique(sous_id):
    questions = Question.query.filter_by(sous_thematique_id=sous_id).all()
    lang = _get_lang()
    results = [_serialize_question(q, lang) for q in questions]
    return jsonify(results)

POSSIBLE_ETHNICITES = [
    "Amérindien ou Autochtone d’Alaska",
    "Asiatique",
    "Noir ou Afro-Américain",
    "Hispanique ou Latino",
    "Moyen-Oriental ou Nord-Africain",
    "Océanien (Hawaïen ou des îles du Pacifique)",
    "Blanc ou Européen Américain"
]

#Authentification: Login
@api_bp.route("/auth/register/request-code", methods=["POST"])
def register_request_code():
    data = request.get_json() or {}
    # on remplace role par ethnicite, et ethnicite devient obligatoire
    required = ["nom","prenom","email","mot_de_passe","telephone","date_naissance","genre","ethnicite"]
    if not all(k in data for k in required):
        return jsonify({"message":"Champs requis manquants"}), 400

    email = data["email"].strip().lower()
    if Utilisateur.query.filter_by(email=email).first():
        return jsonify({"message":"Cet email est déjà utilisé"}), 409

    pwd_hash = bcrypt.hashpw(data["mot_de_passe"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    code = _generate_otp(5)
    otp_hash = _hash(code)
    sent_at = datetime.utcnow().isoformat()

    payload = {
        "user": {
            "nom": data["nom"],
            "prenom": data["prenom"],
            "email": email,
            "mot_de_passe": pwd_hash,
            "date_naissance": data.get("date_naissance"),
            "ethnicite": data.get("ethnicite"),   # <-- NOUVEAU et requis
            "genre": data.get("genre"),
            "telephone": data.get("telephone"),
            "role": "utilisateur",                 # <-- par défaut
        },
        "otp_hash": otp_hash,
        "sent_at": sent_at
    }

    reg_token = _serializer().dumps(payload)

    # Envoi email
    subject = "Votre code de vérification"
    text = f"Votre code de vérification est : {code}\nIl expire dans 10 minutes."
    html = f"""
      <div style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif">
        <p>Votre code de vérification est :</p>
        <p style="font-size:28px;letter-spacing:6px"><b>{code}</b></p>
        <p>Ce code expire dans 10 minutes.</p>
      </div>
    """
    send_email(to=email, subject=subject, text_body=text, html_body=html)

    return jsonify({ "reg_token": reg_token }), 200
@api_bp.route("/auth/register/verify-code", methods=["POST"])
def register_verify_code():
    data = request.get_json() or {}
    reg_token = data.get("reg_token")
    code = (data.get("code") or "").strip()

    if not reg_token or len(code) != 5 or not code.isdigit():
        return jsonify({"message":"Requête invalide"}), 400

    try:
        payload = _serializer().loads(reg_token, max_age=600)  # 10 min
    except SignatureExpired:
        return jsonify({"message":"Code expiré, redemandez un code."}), 400
    except BadSignature:
        return jsonify({"message":"Token invalide"}), 400

    if not _check_hash(code, payload["otp_hash"]):
        return jsonify({"message":"Code invalide"}), 400

    udata = payload["user"]
    # Double check: email pas déjà pris (course condition)
    if Utilisateur.query.filter_by(email=udata["email"]).first():
        return jsonify({"message":"Cet email est déjà utilisé"}), 409

    # Création définitive de l’utilisateur
    u = Utilisateur(
        nom=udata["nom"],
        prenom=udata["prenom"],
        email=udata["email"],
        mot_de_passe=udata["mot_de_passe"],  # déjà hashé
        date_naissance=udata.get("date_naissance"),
        ethnicite=udata.get("ethnicite"),
        genre=udata.get("genre"),
        telephone=udata.get("telephone"),
        role=udata.get("role","utilisateur")
    )
    db.session.add(u)
    db.session.commit()

    # Générer un JWT de session comme dans ta route /auth/login
    token = jwt.encode({
        'id': u.id,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }, current_app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({"message":"Email vérifié, compte créé", "token": token, "user_id": u.id}), 201
from datetime import timezone

@api_bp.route("/auth/register/resend-code", methods=["POST"])
def register_resend_code():
    data = request.get_json() or {}
    reg_token = data.get("reg_token")
    if not reg_token:
        return jsonify({"message":"reg_token requis"}), 400

    try:
        payload = _serializer().loads(reg_token, max_age=600)
    except Exception:
        return jsonify({"message":"Token invalide ou expiré"}), 400

    # cooldown 30s
    try:
        last = datetime.fromisoformat(payload.get("sent_at")).replace(tzinfo=None)
    except Exception:
        last = datetime.utcnow() - timedelta(minutes=1)

    if (datetime.utcnow() - last) < timedelta(seconds=30):
        return jsonify({"message":"Patientez avant de renvoyer un code."}), 429

    code = _generate_otp(5)
    payload["otp_hash"] = _hash(code)
    payload["sent_at"] = datetime.utcnow().isoformat()

    new_reg_token = _serializer().dumps(payload)

    subject = "Nouveau code de vérification"
    email = payload["user"]["email"]
    text = f"Votre nouveau code est : {code}\nIl expire dans 10 minutes."
    html = f"""
      <div style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif">
        <p>Votre nouveau code :</p>
        <p style="font-size:28px;letter-spacing:6px"><b>{code}</b></p>
        <p>Il expire dans 10 minutes.</p>
      </div>
    """
    send_email(to=email, subject=subject, text_body=text, html_body=html)

    return jsonify({ "reg_token": new_reg_token, "message":"Code renvoyé" }), 200

@api_bp.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    mot_de_passe = data.get("mot_de_passe")

    utilisateur = Utilisateur.query.filter_by(email=email).first()
    if utilisateur and bcrypt.checkpw(mot_de_passe.encode('utf-8'), utilisateur.mot_de_passe.encode('utf-8')):
        token = jwt.encode({
            'id': utilisateur.id,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, current_app.config['SECRET_KEY'], algorithm='HS256')

        return jsonify({
            "token": token,
            "id": utilisateur.id,
            "nom": utilisateur.nom,
            "prenom": utilisateur.prenom,
            "email": utilisateur.email
        }), 200
    else:
        return jsonify({"message": "Email ou mot de passe incorrect"}), 401
# ========= Password reset via OTP =========

@api_bp.route("/auth/password/forgot/request", methods=["POST"])
def pw_forgot_request():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"message": "Email requis"}), 400

    user = Utilisateur.query.filter_by(email=email).first()
    if not user:
        # Tu peux renvoyer 200 générique si tu veux éviter de révéler l’existence
        return jsonify({"message": "Si un compte existe pour cet email, un code a été envoyé."}), 200

    code = _generate_otp(5)
    payload = {
        "email": email,
        "user_id": user.id,
        "otp_hash": _hash(code),
        "sent_at": datetime.utcnow().isoformat(),
        "verified": False
    }
    reset_token = _serializer().dumps(payload)

    subject = "Réinitialisation du mot de passe – Code"
    text = f"Votre code est : {code}\nIl expire dans 10 minutes."
    html = f"""
      <div style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif">
        <p>Votre code de réinitialisation :</p>
        <p style="font-size:28px;letter-spacing:6px"><b>{code}</b></p>
        <p>Ce code expire dans 10 minutes.</p>
      </div>
    """
    send_email(to=email, subject=subject, text_body=text, html_body=html)
    return jsonify({"reset_token": reset_token, "message": "Code envoyé"}), 200


@api_bp.route("/auth/password/forgot/resend", methods=["POST"])
def pw_forgot_resend():
    data = request.get_json() or {}
    token = data.get("reset_token")
    if not token:
        return jsonify({"message": "reset_token requis"}), 400
    try:
        payload = _serializer().loads(token, max_age=600)
    except Exception:
        return jsonify({"message": "Token invalide ou expiré"}), 400

    # cooldown 30s
    try:
        last = datetime.fromisoformat(payload.get("sent_at")).replace(tzinfo=None)
    except Exception:
        last = datetime.utcnow() - timedelta(minutes=1)

    if (datetime.utcnow() - last) < timedelta(seconds=30):
        return jsonify({"message":"Patientez avant de renvoyer un code."}), 429

    code = _generate_otp(5)
    payload["otp_hash"] = _hash(code)
    payload["sent_at"] = datetime.utcnow().isoformat()
    payload["verified"] = False

    new_token = _serializer().dumps(payload)

    subject = "Nouveau code – Réinitialisation du mot de passe"
    text = f"Votre nouveau code est : {code}\nIl expire dans 10 minutes."
    html = f"""
      <div style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif">
        <p>Votre nouveau code :</p>
        <p style="font-size:28px;letter-spacing:6px"><b>{code}</b></p>
        <p>Il expire dans 10 minutes.</p>
      </div>
    """
    send_email(to=payload["email"], subject=subject, text_body=text, html_body=html)
    return jsonify({"reset_token": new_token, "message": "Code renvoyé"}), 200


@api_bp.route("/auth/password/forgot/verify", methods=["POST"])
def pw_forgot_verify():
    data = request.get_json() or {}
    token = data.get("reset_token")
    code = (data.get("code") or "").strip()
    if not token or len(code) != 5 or not code.isdigit():
        return jsonify({"message":"Requête invalide"}), 400
    try:
        payload = _serializer().loads(token, max_age=600)
    except BadSignature:
        return jsonify({"message":"Token invalide"}), 400
    except SignatureExpired:
        return jsonify({"message":"Code expiré, redemandez un code."}), 400

    if not _check_hash(code, payload["otp_hash"]):
        return jsonify({"message":"Code invalide"}), 400

    # OK → marquer verified et renvoyer un token rafraîchi
    payload["verified"] = True
    new_token = _serializer().dumps(payload)
    return jsonify({"message": "Code vérifié", "reset_token": new_token}), 200


@api_bp.route("/auth/password/forgot/reset", methods=["POST"])
def pw_forgot_reset():
    data = request.get_json() or {}
    token = data.get("reset_token")
    new_pw = data.get("new_password") or ""
    if not token or not new_pw:
        return jsonify({"message":"reset_token et new_password requis"}), 400
    if len(new_pw) < 8:
        return jsonify({"message":"Le mot de passe doit contenir au moins 8 caractères."}), 400

    try:
        payload = _serializer().loads(token, max_age=1800)  # 30 min pour finir le flow
    except Exception:
        return jsonify({"message":"Token invalide ou expiré"}), 400

    if not payload.get("verified"):
        return jsonify({"message":"Code non vérifié"}), 400

    user = Utilisateur.query.filter_by(email=payload["email"]).first()
    if not user:
        return jsonify({"message":"Utilisateur introuvable"}), 404

    user.mot_de_passe = bcrypt.hashpw(new_pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    db.session.commit()
    return jsonify({"message":"Mot de passe mis à jour"}), 200

# Assuming these are imported at the top:
# from yourapp.models import Admin, Utilisateur, Notification, NotificationUtilisateur
# from flask import request, jsonify
# from yourapp.extensions import db

# Login route (unchanged, already good)
@api_bp.route("/auth/admin/login", methods=["POST"])
def login_login():
    data = request.get_json()
    email = data.get("email")
    mot_de_passe = data.get("mot_de_passe")

    admin = Admin.query.filter_by(email=email).first()
    if admin and bcrypt.checkpw(mot_de_passe.encode('utf-8'), admin.mot_de_passe.encode('utf-8')):
        token = jwt.encode({
            'id': admin.id,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, current_app.config['SECRET_KEY'], algorithm='HS256')

        return jsonify({
            "token": token,
            "id": admin.id,
            "nom": admin.nom,
            "prenom": admin.prenom,
            "email": admin.email
        }), 200
    else:
        return jsonify({"message": "Email ou mot de passe incorrect"}), 401

# Send notification
#Admin
from .mailer import send_email

@api_bp.route('/notifications/send', methods=['POST'])
def send_notification():
    data = request.get_json() or {}
    titre = data.get('titre')
    contenu = data.get('contenu')
    utilisateur_ids = data.get('utilisateur_ids')
    broadcast = data.get('broadcast')

    if not titre or not contenu:
        return jsonify({"message": "titre et contenu sont requis"}), 400

    users = []
    if broadcast is True or utilisateur_ids in ("all", "*"):
        users = Utilisateur.query.all()
    else:
        if not utilisateur_ids or not isinstance(utilisateur_ids, list):
            return jsonify({"message": "utilisateur_ids (liste) ou broadcast=true est requis"}), 400
        users = Utilisateur.query.filter(Utilisateur.id.in_(utilisateur_ids)).all()
    users_by_id = {u.id: u for u in users}
    users = list(users_by_id.values())

    # 1) Creation de la notif + liaisons
    notif = Notification(titre=titre, contenu=contenu)
    db.session.add(notif)
    db.session.flush()

    destinataires = []
    for user in users:
        liaison = NotificationUtilisateur(utilisateur=user, notification=notif)
        db.session.add(liaison)
        if user.email:
            destinataires.append(user)
    db.session.commit()  # commit avant d'envoyer les emails
    # 2) Construction du contenu de l’email
    base_url = current_app.config.get("FRONTEND_BASE_URL", "").rstrip("/")
    # Si vous avez une page "Notifications", ajustez le lien selon votre frontend
    lien = f"{base_url}/notifications" if base_url else None

    subject = f"[Notification] {titre}"
    def build_bodies(u):
        text = f"""{contenu}

{"Voir la notification : " + lien if lien else ""}
— Envoyé par Ma Plateforme
"""
        html = f"""
        <div style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif">
          <p>{contenu}</p>
          {f'<p><a href="{lien}" target="_blank">Voir la notification sur la plateforme</a></p>' if lien else ""}
          <hr>
          <small>Envoyé par Ma Plateforme</small>
        </div>
        """
        return text, html

    # 3) Envoi
    emails_sent = 0
    failures = []
    for u in destinataires:
        text_body, html_body = build_bodies(u)
        ok = send_email(
            to=u.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body
        )
        if ok:
            emails_sent += 1
        else:
            failures.append({"user_id": u.id, "email": u.email})

    return jsonify({
        "message": "Notification envoyée",
        "notification": {
          "id": notif.id,
          "titre": notif.titre,
          "contenu": notif.contenu,
          "date_envoi": notif.date_envoi.isoformat() if notif.date_envoi else None
        },
        "email_summary": {
          "attempted": len(destinataires),
          "sent": emails_sent,
          "failed": failures
        }
    }), 201

# Get notifications for a user
@api_bp.route('/notifications/<int:user_id>', methods=['GET'])
def get_notifications_for_user(user_id):
    """
    Notifications d'un utilisateur (paginées).
    Params:
      - page, per_page
      - q: recherche plein texte sur titre/contenu
      - est_lu: true/false (accepte aussi 1/0, oui/non)
      - date_from, date_to: ISO (YYYY-MM-DD ou datetime ISO)
      - sort: champs de Notification, ex "-date_envoi,id" (défaut)
    """
    # 404 si l'utilisateur n'existe pas
    Utilisateur.query.get_or_404(user_id)

    page, per_page = get_pagination_params()

    q = (
        db.session.query(Notification, NotificationUtilisateur.est_lu)
        .join(NotificationUtilisateur, NotificationUtilisateur.notification_id == Notification.id)
        .filter(NotificationUtilisateur.utilisateur_id == user_id)
    )

    # Recherche texte
    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Notification.titre.ilike(s),
                         Notification.contenu.ilike(s)))

    # Filtre est_lu
    est_lu_param = request.args.get("est_lu")
    if est_lu_param is not None:
        v = est_lu_param.strip().lower()
        if v in ("true", "1", "t", "yes", "y", "vrai", "oui"):
            q = q.filter(NotificationUtilisateur.est_lu.is_(True))
        elif v in ("false", "0", "f", "no", "n", "faux", "non"):
            q = q.filter(NotificationUtilisateur.est_lu.is_(False))
        else:
            abort(400, description="`est_lu` doit être true/false (ou 1/0, oui/non).")

    # Filtres de date (sur Notification.date_envoi)
    def _parse_from(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                d = _date.fromisoformat(value)
                return datetime.combine(d, _time.min)
            except ValueError:
                abort(400, description="`date_from` doit être YYYY-MM-DD ou datetime ISO.")

    def _parse_to(value):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                d = _date.fromisoformat(value)
                return datetime.combine(d, _time.max)
            except ValueError:
                abort(400, description="`date_to` doit être YYYY-MM-DD ou datetime ISO.")

    date_from = request.args.get("date_from")
    if date_from:
        q = q.filter(Notification.date_envoi >= _parse_from(date_from))

    date_to = request.args.get("date_to")
    if date_to:
        q = q.filter(Notification.date_envoi <= _parse_to(date_to))

    # Tri (on autorise les champs de Notification ; défaut: plus récentes d'abord)
    q = apply_sorting(q, Notification, default="-date_envoi,id")

    # Total
    total = q.order_by(None).with_entities(func.count(Notification.id)).scalar()

    # Page
    rows = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [{
        "notification_id": n.id,
        "titre": n.titre,
        "contenu": n.contenu,
        "date_envoi": n.date_envoi.isoformat() if n.date_envoi else None,
        "est_lu": est_lu
    } for (n, est_lu) in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))
# Mark a notification as read
@api_bp.route('/notifications/<int:user_id>/<int:notification_id>/read', methods=['PUT'])
def mark_as_read(user_id, notification_id):
    liaison = NotificationUtilisateur.query.filter_by(
        utilisateur_id=user_id,
        notification_id=notification_id
    ).first_or_404()

    liaison.est_lu = True
    db.session.commit()

    notif = liaison.notification
    return jsonify({
      "message": "Notification marquée comme lue",
      "notification": {
        "id":    notif.id,
        "titre": notif.titre
      }
    })
@api_bp.route('/notifications/<int:user_id>/<int:notification_id>/unread', methods=['PUT'])
def mark_as_unread(user_id, notification_id):
    liaison = NotificationUtilisateur.query.filter_by(
        utilisateur_id=user_id,
        notification_id=notification_id
    ).first_or_404()

    liaison.est_lu = False
    db.session.commit()

    notif = liaison.notification
    return jsonify({
        "message": "Notification marquée comme non lue",
        "notification": {
            "id":    notif.id,
            "titre": notif.titre
        }
    }), 200
# Admin – historique global des notifications (paginé)
@api_bp.route('/notifications', methods=['GET'])
def get_all_notifications():
    """
    Historique global des notifications.
    Params:
      - page, per_page
      - q (titre/contenu)
      - date_from, date_to (sur Notification.date_envoi)
      - sort: champs de Notification, ex "-date_envoi,id" (défaut)
    """
    page, per_page = get_pagination_params()

    q = Notification.query

    search = request.args.get("q")
    if search:
        s = f"%{search}%"
        q = q.filter(or_(Notification.titre.ilike(s),
                         Notification.contenu.ilike(s)))

    def _parse_iso_date(val, end_of_day=False):
        try:
            dt = datetime.fromisoformat(val)
            return dt
        except ValueError:
            d = _date.fromisoformat(val)
            return datetime.combine(d, _time.max if end_of_day else _time.min)

    date_from = request.args.get("date_from")
    if date_from:
        q = q.filter(Notification.date_envoi >= _parse_iso_date(date_from))

    date_to = request.args.get("date_to")
    if date_to:
        q = q.filter(Notification.date_envoi <= _parse_iso_date(date_to, end_of_day=True))

    q = apply_sorting(q, Notification, default="-date_envoi,id")

    total = q.order_by(None).with_entities(func.count(Notification.id)).scalar()
    rows  = q.limit(per_page).offset((page - 1) * per_page).all()

    items = [{
        "id": n.id,
        "titre": n.titre,
        "contenu": n.contenu,
        "date_envoi": n.date_envoi.isoformat() if n.date_envoi else None
    } for n in rows]

    return jsonify(build_paginated_response(items, total, page, per_page))

# dashboard 
POSSIBLE_ETHNICITES = [
    "Amérindien ou Autochtone d’Alaska",
    "Asiatique",
    "Noir ou Afro-Américain",
    "Hispanique ou Latino",
    "Moyen-Oriental ou Nord-Africain",
    "Océanien ",
    "Blanc ou Européen Américain"
]

@api_bp.route('/ethnicity-distribution', methods=['GET'])
def ethnicity_distribution():
    # 1) Construire une liste de conditions "ethnicite LIKE 'valeur%'" (début de chaîne)
    conditions = [
        Utilisateur.ethnicite.ilike(f"{eth}%")
        for eth in POSSIBLE_ETHNICITES
    ]

    # 2) Exécuter la requête agrégée en une fois
    rows = (
        db.session.query(
            Utilisateur.ethnicite.label('ethnicite'),
            Utilisateur.genre.label('genre'),
            func.count(Utilisateur.id).label('count')
        )
        .filter(
            or_(*conditions),                      # filtre "début de chaîne"
            Utilisateur.genre.in_(['Femme', 'Homme'])
        )
        .group_by(Utilisateur.ethnicite, Utilisateur.genre)
        .all()
    )

    # 3) Réassembler les résultats selon votre liste fixe
    labels = POSSIBLE_ETHNICITES
    counts = {'Homme': [], 'Femme': []}

    for eth in labels:
        for gen in ('Femme', 'Homme'):
            # on cherche le count sur les rows dont ethnicite commence par eth et genre = gen
            cnt = next(
                (r.count for r in rows
                 if r.ethnicite.lower().startswith(eth.lower()) and r.genre == gen),
                0
            )
            counts[gen].append(cnt)

    # 4) Retour JSON prêt pour votre front
    return jsonify({
        'labels': labels,
        'Femme': counts['Femme'],
        'Homme': counts['Homme']
    })

@api_bp.route("/thematiques/progress", methods=["GET"])
def thematiques_progress():
    # 1) Tous les utilisateurs « participants »
    users = Utilisateur.query.all()
    total_users = len(users)

    # 2) Charger les thématiques avec leurs sous-thématiques et questions
    thematiques = (
        Thematique.query
        .options(
            # on “joined-load” d’abord les sous-thématiques,
            # puis pour chacune on joined-load les questions
            joinedload(Thematique.sous_thematiques)
            .joinedload(SousThematique.questions)
        )
        .all()
    )

    result = []
    for t in thematiques:
        # Rassembler tous les IDs de questions pour cette thématique
        question_ids = [
            q.id
            for st in t.sous_thematiques
            for q in st.questions
        ]
        nb_questions = len(question_ids)

        if nb_questions == 0:
            # Aucun question => personne ne peut la compléter
            completed = 0
            incomplete = total_users
        else:
            # Compter pour chaque utilisateur s’il a répondu à toutes les questions
            completed = 0
            for u in users:
                count_responses = (
                    Reponse.query
                    .filter(
                        Reponse.utilisateur_id == u.id,
                        Reponse.question_id.in_(question_ids)
                    )
                    .count()
                )
                if count_responses == nb_questions:
                    completed += 1
            incomplete = total_users - completed

        result.append({
            "id": t.id,
            "name": t.name,
            "completed_count": completed,
            "incomplete_count": incomplete
        })

    return jsonify(result)

@api_bp.route('/age-distribution', methods=['GET'])
def age_distribution():
    # tranches fixes
    labels = ['0-17', '18-30', '31-45', '46-60', '60+', 'Inconnu']
    counts = {label: 0 for label in labels}

    today = date.today()
    # récupère tous les utilisateurs ayant une date de naissance
    users = Utilisateur.query.filter(Utilisateur.date_naissance.isnot(None)).all()

    for u in users:
        # calcul âge en années (entier)
        delta = today - u.date_naissance
        age = delta.days // 365 if delta.days >= 0 else None

        if age is None:
            bracket = 'Inconnu'
        elif age < 18:
            bracket = '0-17'
        elif age <= 30:
            bracket = '18-30'
        elif age <= 45:
            bracket = '31-45'
        elif age <= 60:
            bracket = '46-60'
        else:
            bracket = '60+'

        counts[bracket] += 1

    return jsonify({
        'labels': labels,
        'counts': [counts[b] for b in labels]
    })
