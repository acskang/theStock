#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/thestock/thestock.env"
PYTHON_BIN="${PYTHON_BIN:-/home/cskang/miniconda3/envs/dj5/bin/python}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

set -a
. "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE=stock_service.settings.prod

"$PYTHON_BIN" manage.py check
curl --silent --show-error --fail --unix-socket /run/gunicorn_thestock.sock -H 'Host: stock.thesysm.com' -H 'X-Forwarded-Proto: https' http://localhost/healthz/
curl --silent --show-error --fail --unix-socket /run/gunicorn_thestock.sock -H 'Host: stock.thesysm.com' -H 'X-Forwarded-Proto: https' http://localhost/readyz/
sudo systemctl status gunicorn_thestock.service --no-pager --lines=0
sudo systemctl status nginx --no-pager --lines=0
sudo systemctl status cloudflared --no-pager --lines=0
