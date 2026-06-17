## theStock Production Deployment Assets

These files are the source-controlled deployment assets for theStock.

Target topology:

- Cloudflare Tunnel
- Nginx
- Gunicorn
- Django (`stock_service.settings.prod`)

Installed targets:

- systemd service: `/etc/systemd/system/gunicorn_thestock.service`
- environment file: `/etc/thestock/thestock.env`
- nginx site: `/etc/nginx/sites-available/thestock`
- nginx symlink: `/etc/nginx/sites-enabled/thestock`
- cloudflared ingress fragment: merge into `/etc/cloudflared/config.yml`

Runtime paths:

- public socket path: `/run/gunicorn_thestock.sock`
- actual socket path: `/run/thestock/gunicorn.sock`
- static alias root: `/var/www/thestock/static`
- media alias root: `/var/www/thestock/media`
- application logs: `/logs/thestock`

Notes:

- `manage.py` remains local-development friendly and defaults to `stock_service.settings.dev`.
- Gunicorn must set `DJANGO_SETTINGS_MODULE=stock_service.settings.prod`.
- Secrets must live only in `/etc/thestock/thestock.env`.
- Gunicorn process runs as user `cskang` and group `www-data`.
- systemd creates `/run/thestock/` as the writable runtime directory.
- Peach auth relay should use `THEPEACH_AUTH_BASE_URL=http://127.0.0.1` and `THEPEACH_UPSTREAM_HOST_HEADER=peach.thesysm.com`.
- For a manual deployment run, use `deploy/production/run_thestock_deploy.sh`.
