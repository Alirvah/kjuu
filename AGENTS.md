# AGENTS.md

## Purpose
This document defines the expected engineering workflow for changes in this repository.

## Project context
- Stack: Django 5, PostgreSQL (production), Docker Compose.
- App: virtual queue management with owner dashboard and customer join flow.
- Security baseline: mutating endpoints are POST-only with CSRF protection.
- Localization: Django i18n with Slovak (`sk`) and English (`en`).

## Working rules
- Use relative paths in shell commands from repo root.
- Prefer small, focused commits grouped by behavior.
- Never weaken authz/authn checks to satisfy tests.
- Keep templates and backend messages translatable.
- Preserve queue invariants:
  - one queue per owner account,
  - one active customer queue membership per account,
  - owner-only queue management actions.

## Required checks before merge
Run all commands from repository root.

1. Build container image:
`docker compose build web`

2. Compile translations:
`docker compose run --rm --no-deps --user root -e DJANGO_SECURE_STRING=test -e DOMAIN_NAME=kjuu.local -e APP_NAME=kjuu -e DATABASE_URL=sqlite:////tmp/kjuu.db web python manage.py compilemessages`

3. Run tests:
`docker compose run --rm --no-deps -e DJANGO_SECURE_STRING=test -e DOMAIN_NAME=kjuu.local -e APP_NAME=kjuu -e DATABASE_URL=sqlite:////tmp/kjuu.db web pytest -q`

4. Run deploy checks:
`docker compose run --rm --no-deps -e DJANGO_SECURE_STRING=test -e DOMAIN_NAME=kjuu.local -e APP_NAME=kjuu -e DATABASE_URL=sqlite:////tmp/kjuu.db web python manage.py check --deploy`

## Testing expectations
- Every URL in `queueapp/urls.py` must have route-level coverage.
- New mutating behavior must include method tests (`GET` rejection + valid `POST`).
- Security-sensitive endpoints must test permission boundaries and malformed payloads.
- New translated copy should have at least one language-switch assertion.

## Documentation expectations
- Update `README.md` when setup, env vars, endpoints, or behavior changes.
- Keep legal pages aligned with implemented data flow.
- If adding new user-facing text, mark it for translation.
