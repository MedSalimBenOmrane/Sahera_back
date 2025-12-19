# Sahera - Backend API

Flask backend for Sahera that powers themes, questionnaires, notifications, and OTP flows with JWT auth. This README walks through requirements, code navigation, behaviors (24h session expiry, OTP), and deployment.

## Quick View
- REST API under `/api` (Flask + SQLAlchemy + PostgreSQL).
- JWT auth (24h) for users and admins; signup and password reset by email OTP.
- Themes / subthemes / questions (list, text, date) with CSV import.
- Notifications stored in DB + email delivery; demographic stats and theme progress.
- Dockerized; targets AWS Elastic Beanstalk + RDS.

## Architecture (AWS)
![AWS Architecture](app/assets/aws%20architecture.jpg)

## Data Model
![Class Diagram](app/assets/diagramme%20classe.png)

## Tech Stack
- Python 3.12, Flask, Flask-SQLAlchemy, Flask-Migrate.
- PostgreSQL 15+.
- Gunicorn in production; Dockerfile and docker-compose included.
- SMTP (Gmail by default) for OTP and notification emails.

## Repository Structure
- `main.py`: Flask entrypoint.
- `app/__init__.py`: app factory, CORS, DB/JWT/SMTP config, registers the `/api` blueprint.
- `app/routes.py`: main routes (auth, CRUD themes/subthemes/questions/answers, notifications, stats).
- `app/models.py`: SQLAlchemy models (Thematique, SousThematique, Question, Utilisateur, Admin, Reponse, Notification, NotificationUtilisateur).
- `app/mailer.py`: email sending (OTP, notifications) with inline QR code; SMTP override by Admin.
- `app/auth_simple.py`: JWT helpers (issue_token, blacklist, decorator) if you need to protect routes.
- `migrations/`: Flask-Migrate scripts.
- `.ebextensions/`, `.elasticbeanstalk/`: Elastic Beanstalk config (healthcheck, Docker platform).
- `app/assets/`: visuals (diagrams, QR).

## Core Features
- **Auth & accounts**
  - Two-step signup: `/auth/register/request-code` sends a 5-digit OTP (expires in 10 min); `/auth/register/verify-code` creates the account and returns a 24h JWT. Resend OTP with 30s cooldown.
  - User login: `/auth/login` -> JWT (24h). Admin login: `/auth/admin/login` -> JWT (24h). Clients should clear the token or re-auth after a 401 since it expires automatically.
  - Password reset via OTP (`/auth/password/forgot/*`), verify then reset.
- **Themes / questionnaires**
  - CRUD themes (FR/EN fields, open/close dates), subthemes, and questions (types `liste`, `text`, `date`, bilingual options).
  - CSV import for subthemes/questions of a theme (`/thematiques/<id>/import_csv`).
  - User answers linked to questions; listings by subtheme and by user.
  - Dedicated endpoints for completed/incomplete themes per user and global progress (`/thematiques/progress`).
  - `lang=fr|en` returns localized labels.
- **Notifications**
  - Create targeted notifications, store in DB, link to users, mark read/unread, filter/paginate/sort, optional email send (`/notifications/*`).
- **Dashboard stats**
  - Ethnicity/gender distribution (`/ethnicity-distribution`), age buckets (`/age-distribution`), theme progress (`/thematiques/progress`).
- **Misc**
  - Health check `/health`.
  - Uniform pagination/sort (`page`, `per_page`, `sort`) and search (`q`) across lists.

## API at a Glance
- Base path: `/api`.
- Auth: `Authorization: Bearer <token>` (JWT 24h). No refresh token: re-login after expiry or 401.
- Locale: `lang=fr|en` to localize theme/subtheme/question/answer labels.
- Pagination/sort: `page`, `per_page`, `sort` (e.g., `name,-date_ouverture`).
- Main endpoint blocks:
  - Auth/OTP: `/auth/register/*`, `/auth/login`, `/auth/admin/login`, `/auth/password/forgot/*`.
  - Themes: `/thematiques`, `/thematiques/ouvertes`, `/thematiques/fermees`, `/thematiques/<id>/details`, CSV import, progress/completion.
  - Subthemes & questions: CRUD under `/thematiques/<id>/sousthematiques` and `/questions`.
  - Answers: `/reponses` CRUD, answers of a user for a subtheme, etc.
  - Users/Admins: basic CRUD (`/utilisateurs`, `/admins`).
  - Notifications: `/notifications/send`, `/notifications/<user_id>`, mark read/unread, admin history.
  - Stats: `/ethnicity-distribution`, `/age-distribution`, `/thematiques/progress`.

## Configuration (env vars)
Do not commit secrets. The root `.env` currently contains real values: replace them before pushing or create a `.env.example` without secrets. Key vars:

| Variable | Description / Example |
| --- | --- |
| `DATABASE_URL` | Postgres URL (e.g., `postgresql+psycopg2://user:pass@host:5432/db`). Fallback via `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`. |
| `SECRET_KEY` / `JWT_SECRET_KEY` | App key and JWT signing key. |
| `CORS_ORIGINS` / `FRONTEND_BASE_URL` | Allowed frontend origins (e.g., `http://localhost:4200`). |
| `MAIL_SENDER_EMAIL`, `MAIL_SENDER_NAME` | Default email sender. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_TIMEOUT` | SMTP config for OTP/notifications. |
| `FLASK_APP`, `FLASK_ENV`, `FLASK_DEBUG` | Flask runtime settings. |
| `PORT` | Gunicorn listen port (Elastic Beanstalk injects it). |

## Local Setup (no Docker)
1) Install Python 3.12 and Postgres.  
2) Create a venv and install deps:  
```
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```
3) Copy `.env` or set env vars (`DATABASE_URL` or DB_*, `SECRET_KEY`, `JWT_SECRET_KEY`, SMTP).  
4) Init DB: `flask db upgrade` (set `FLASK_APP=main.py`).  
5) Run dev server: `flask --app main run --debug` (CORS set in `app/__init__.py`).  
Gunicorn is used in prod via `entrypoint.sh`.

## Docker Setup
```
docker-compose up --build
```
- API on `http://localhost:5000` (mapped from container port 80).
- Postgres service `db`; Adminer at `http://localhost:8080`.
- `entrypoint.sh` runs `flask db upgrade` (5 attempts) before starting Gunicorn.

## Migrations
- Create: `flask db migrate -m "message"`  
- Apply: `flask db upgrade`  
- Scripts live in `migrations/`.

## Deployment (AWS Elastic Beanstalk)
- Platform: Docker on Amazon Linux 2023 (`.elasticbeanstalk/config.yml`).
- Custom healthcheck in `.ebextensions/01-healthcheck.config`.
- Deploy flow: build image, EB deploys, `entrypoint.sh` runs migrations then Gunicorn.
- Target DB: RDS Postgres (see AWS diagram above). Set `DATABASE_URL` and secrets via EB env vars.

## Dev Notes / Gotchas
- JWT expires after 24h (users and admins): front should refresh or re-login on 401.
- OTP (signup/reset) valid 10 min; resend allowed after 30s.
- Bilingual options: `options` and `options_en` must have the same length for `liste` questions.
- CSV import: required headers `sous_thematique,question,type,options` (+ optional `_en` variants); separators `|`, `;`, or `,`.
- Notifications: stored in DB then email is sent; frontend can link to `/notifications`.

## Visuals
- AWS architecture: `app/assets/aws architecture.jpg`
- Class diagram: `app/assets/diagramme classe.png`

## Support
If you need more details on endpoints or the EB pipeline, ask. EB logs live in `.elasticbeanstalk/logs/`; Adminer helps with local SQL debugging.
