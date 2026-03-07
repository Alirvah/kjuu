# kjuu

kjuu is a Django-based virtual queue application. Queue owners create a queue and serve customers in FIFO order. Customers join by queue code/QR and track live position from the browser.

## Highlights
- Queue creation with generated QR PDF.
- Customer join/leave flow with live position.
- Owner dashboard for pause/resume, call-next, and queue stats.
- Optional end-to-end encrypted customer note.
- Bilingual UI (Slovak/English) with global language switch.
- Security hardening: CSRF-protected POST mutations and stricter JSON endpoint authorization.

## Tech stack
- Python 3.12
- Django 5.x
- PostgreSQL (production)
- Docker + Docker Compose
- Pytest + pytest-django

## Quick start (Docker)
Run all commands from repository root.

1. Build image:
`docker compose build web`

2. Start database and app:
`docker compose up -d db web`

3. Apply migrations:
`docker compose run --rm web python manage.py migrate`

4. Create superuser:
`docker compose run --rm web python manage.py createsuperuser`

The app is exposed on port `8030` by default (`http://localhost:8030`).

## Environment variables
Required by settings:
- `DJANGO_SECURE_STRING`
- `DOMAIN_NAME`
- `APP_NAME`
- `DATABASE_URL`

See `.env.template` for a base template.

## Testing
Use the containerized test command with explicit runtime envs:

`docker compose run --rm --no-deps -e DJANGO_SECURE_STRING=test -e DOMAIN_NAME=kjuu.local -e APP_NAME=kjuu -e DATABASE_URL=sqlite:////tmp/kjuu.db web pytest -q`

Deploy checks:

`docker compose run --rm --no-deps -e DJANGO_SECURE_STRING=test -e DOMAIN_NAME=kjuu.local -e APP_NAME=kjuu -e DATABASE_URL=sqlite:////tmp/kjuu.db web python manage.py check --deploy`

## Translation workflow
The app uses Django i18n with `sk` and `en`.

Compile existing translations:

`docker compose run --rm --no-deps --user root -e DJANGO_SECURE_STRING=test -e DOMAIN_NAME=kjuu.local -e APP_NAME=kjuu -e DATABASE_URL=sqlite:////tmp/kjuu.db web python manage.py compilemessages`

If new translatable strings are added, generate message catalogs first (if needed), then compile.

## API/route overview
Main routes are in `queueapp/urls.py`:
- Public: `/`, `/signup/`, `/login/`, `/privacy/`, `/terms/`
- Queue lifecycle: `/queue/create/`, `/queue/<short_id>/join/`, `/queue/go/`
- Owner actions: `/queue/<short_id>/dashboard/`, `/queue/<short_id>/call_next/`, `/queue/<short_id>/pause/`, `/queue/<short_id>/delete/`
- Customer action: `/queue/<short_id>/leave/`
- QR download: `/queue/<short_id>/qr/`
- Crypto/info JSON endpoints:
  - `/q/<short_id>/register_key/`
  - `/q/<short_id>/submit_info/`
  - `/q/<short_id>/clear_info/`

Important: mutating endpoints are POST-only.

## Security notes
- CSRF middleware enabled and mutating operations require POST.
- Rate limiting is applied to signup/login/join/navigation helpers.
- Secure-cookie and HTTPS settings are enabled by default when `DEBUG=False`.
- Account/queue ownership checks are enforced server-side.

## Repo structure
- `kjuu/` Django project settings and root URL config
- `queueapp/` app logic, models, views, tests
- `templates/queueapp/` UI templates
- `static/` app CSS/JS/assets
- `locale/` translation catalogs

## Legal pages
Privacy Policy and Terms are under:
- `/privacy/`
- `/terms/`

They are translated and rendered through the same language-switch mechanism as the rest of the app.
