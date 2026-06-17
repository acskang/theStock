#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="/etc/thestock/thestock.env"
PYTHON_BIN="${PYTHON_BIN:-/home/cskang/miniconda3/envs/dj5/bin/python}"
PUBLIC_DOMAIN="${THESTOCK_PUBLIC_DOMAIN:-stock.thesysm.com}"
THEPEACH_PUBLIC_DOMAIN="${THEPEACH_PUBLIC_DOMAIN:-peach.thesysm.com}"
THEPEACH_ORIGIN_BASE_URL="${THEPEACH_ORIGIN_BASE_URL:-http://127.0.0.1}"

cd "$ROOT_DIR"

sudo mkdir -p /etc/thestock /var/www/thestock /logs/thestock
sudo chown cskang:www-data /logs/thestock
sudo chmod 775 /logs/thestock

mkdir -p "$ROOT_DIR/media"

if [ ! -f "$ENV_FILE" ]; then
  secret_key="$($PYTHON_BIN - <<'PY'
import secrets

print(secrets.token_urlsafe(50))
PY
)"
  tmp_env="$(mktemp)"
  cat > "$tmp_env" <<EOF
DJANGO_SECRET_KEY=${secret_key}
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=${PUBLIC_DOMAIN}
DJANGO_CSRF_TRUSTED_ORIGINS=https://${PUBLIC_DOMAIN}
DJANGO_SETTINGS_MODULE=stock_service.settings.prod
DJANGO_LOG_DIR=/logs/thestock
DJANGO_LOG_LEVEL=INFO
DJANGO_TIME_ZONE=Asia/Seoul
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=true
DJANGO_SECURE_HSTS_PRELOAD=true
POSTGRES_DB=stock_workbench
POSTGRES_USER=stock_workbench
POSTGRES_PASSWORD=
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
APP_VERSION=prod
APP_BUILD_SHA=unknown
READINESS_CHECK_MIGRATIONS=1
LEGACY_PORTFOLIO_USERNAME=demo
OPENDART_API_KEY=
DATA_PIPELINE_PROVIDER=auto
STATIC_URL=/static/
STATIC_ROOT=${ROOT_DIR}/staticfiles
MEDIA_URL=/media/
MEDIA_ROOT=${ROOT_DIR}/media
THEPEACH_AUTH_BASE_URL=${THEPEACH_ORIGIN_BASE_URL}
THEPEACH_LOGIN_BASE_URL=${THEPEACH_ORIGIN_BASE_URL}
THEPEACH_PUBLIC_BASE_URL=https://${THEPEACH_PUBLIC_DOMAIN}
THEPEACH_UPSTREAM_HOST_HEADER=${THEPEACH_PUBLIC_DOMAIN}
THEPEACH_SSO_COOKIE_DOMAIN=.thesysm.com
THEPEACH_SSO_COOKIE_SAMESITE=Lax
THEPEACH_SSO_COOKIE_SECURE=true
THEPEACH_AUTH_TIMEOUT=10
EOF
  sudo install -m 640 -o root -g cskang "$tmp_env" "$ENV_FILE"
  rm -f "$tmp_env"
  echo "Created $ENV_FILE"
fi

sudo install -m 644 -o root -g root deploy/production/gunicorn_thestock.service /etc/systemd/system/gunicorn_thestock.service
sudo install -m 644 -o root -g root deploy/production/nginx_thestock.conf /etc/nginx/sites-available/thestock
sudo ln -sfn /etc/nginx/sites-available/thestock /etc/nginx/sites-enabled/thestock

sudo ln -sfn "$ROOT_DIR/staticfiles" /var/www/thestock/static
sudo ln -sfn "$ROOT_DIR/media" /var/www/thestock/media

if ! sudo grep -q "hostname: ${PUBLIC_DOMAIN}" /etc/cloudflared/config.yml; then
  sudo cp /etc/cloudflared/config.yml "/etc/cloudflared/config.yml.bak.thestock.$(date +%Y%m%d%H%M%S)"
  export PUBLIC_DOMAIN
  sudo -E python3 - <<'PY'
from pathlib import Path
import os

path = Path("/etc/cloudflared/config.yml")
text = path.read_text()
public_domain = os.environ["PUBLIC_DOMAIN"]
needle = "  - service: http_status:404\n"
block = f"""  # theStock
  - hostname: {public_domain}
    service: http://localhost
    originRequest:
      unixSocketPath: /run/gunicorn_thestock.sock
      httpHostHeader: {public_domain}

"""
if f"hostname: {public_domain}" not in text:
    if needle in text:
        text = text.replace(needle, block + needle)
    else:
        if not text.endswith("\\n"):
            text += "\\n"
        text += block
path.write_text(text)
PY
fi

set -a
. "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE=stock_service.settings.prod

if [ "${SKIP_PIP_INSTALL:-0}" != "1" ]; then
  "$PYTHON_BIN" -m pip install -r requirements.txt
fi
"$PYTHON_BIN" manage.py collectstatic --noinput
"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" manage.py check --deploy

sudo systemctl daemon-reload
sudo rm -f /run/gunicorn_thestock.sock
sudo systemctl enable gunicorn_thestock.service
sudo systemctl restart gunicorn_thestock.service
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl restart cloudflared

echo "theStock production deployment files installed."
