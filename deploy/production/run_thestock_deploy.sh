#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="/etc/thestock/thestock.env"
PYTHON_BIN="${PYTHON_BIN:-/home/cskang/miniconda3/envs/dj5/bin/python}"
PUBLIC_DOMAIN="${THESTOCK_PUBLIC_DOMAIN:-stock.thesysm.com}"
THEPEACH_PUBLIC_DOMAIN="${THEPEACH_PUBLIC_DOMAIN:-peach.thesysm.com}"
THEPEACH_ORIGIN_BASE_URL="${THEPEACH_ORIGIN_BASE_URL:-http://127.0.0.1}"

cd "$ROOT_DIR"

echo "[1/4] Refreshing production env file"

secret_key="$($PYTHON_BIN -c 'import secrets; print(secrets.token_urlsafe(50))')"
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
APP_BUILD_SHA=manual
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

if sudo test -f "$ENV_FILE"; then
  sudo cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
fi

sudo mkdir -p /etc/thestock
sudo install -m 640 -o root -g cskang "$tmp_env" "$ENV_FILE"
rm -f "$tmp_env"

echo "[2/4] Installing deployment files"
bash deploy/production/install_thestock.sh

echo "[3/4] Validating deployment"
bash deploy/production/validate_thestock.sh

echo "[4/4] Completed"
echo "Production URL: https://${PUBLIC_DOMAIN}"
