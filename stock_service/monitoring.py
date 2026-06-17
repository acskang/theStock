from __future__ import annotations

from django.conf import settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.utils import timezone


def _build_base_payload():
    return {
        "service": "stock-workbench",
        "version": getattr(settings, "APP_VERSION", "dev"),
        "build_sha": getattr(settings, "APP_BUILD_SHA", "-"),
        "timestamp": timezone.now().isoformat(),
    }


def _check_default_database():
    try:
        connection = connections["default"]
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return {
            "ok": False,
            "alias": "default",
            "error_type": exc.__class__.__name__,
        }
    return {
        "ok": True,
        "alias": "default",
    }


def _check_pending_migrations():
    try:
        connection = connections["default"]
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)
    except Exception as exc:
        return {
            "ok": False,
            "error_type": exc.__class__.__name__,
        }
    return {
        "ok": len(plan) == 0,
        "pending_count": len(plan),
    }


def healthz(_request):
    payload = _build_base_payload()
    payload["status"] = "ok"
    return JsonResponse(payload, status=200)


def readyz(_request):
    payload = _build_base_payload()
    database_check = _check_default_database()

    if getattr(settings, "READINESS_CHECK_MIGRATIONS", True) and database_check["ok"]:
        migration_check = _check_pending_migrations()
    else:
        migration_check = {
            "ok": True,
            "skipped": True,
        }

    overall_ok = database_check["ok"] and migration_check["ok"]
    payload.update(
        {
            "status": "ready" if overall_ok else "not_ready",
            "checks": {
                "database": database_check,
                "migrations": migration_check,
            },
        }
    )
    return JsonResponse(payload, status=200 if overall_ok else 503)
