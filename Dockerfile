# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# ---- dependencies (cached unless requirements.txt changes) --------------------------------------
FROM base AS deps
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---- runtime ------------------------------------------------------------------------------------
FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY --from=deps /install /usr/local
COPY . .

# Static files for the admin, compressed and served by WhiteNoise. The build-only secret is never
# used at runtime; real secrets are injected as environment variables.
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

USER app

# Secure by default: this image is the production artifact. Override for plain-HTTP local runs.
ENV DJANGO_ENFORCE_HTTPS=true \
    WEB_CONCURRENCY=2
EXPOSE 8000

# Migrations are NOT run here. Run them as a one-off job before rolling out a new revision:
#   python manage.py migrate --noinput && python manage.py createcachetable
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--timeout", "60", "--graceful-timeout", "30"]
