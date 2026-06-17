from django.conf import settings
from django.core.management.base import BaseCommand

from holdings.services.sync_service import sync_all_holdings_for_legacy_user


class Command(BaseCommand):
    help = "legacy portfolio.Transaction 을 지정 사용자 UserHolding 으로 동기화합니다."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=settings.LEGACY_PORTFOLIO_USERNAME)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        username = options["username"]
        dry_run = options["dry_run"]

        report = sync_all_holdings_for_legacy_user(
            username=username,
            commit=not dry_run,
        )

        mode = "DRY-RUN" if dry_run else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] holding sync complete "
                f"(created={report.created_count}, updated={report.updated_count}, "
                f"deactivated={report.deactivated_count}, unresolved={len(set(report.unresolved_names))})"
            )
        )
        if report.unresolved_names:
            unresolved = ", ".join(sorted(set(report.unresolved_names)))
            self.stdout.write(self.style.WARNING(f"Unresolved stock names: {unresolved}"))
        if report.warnings:
            self.stdout.write(self.style.WARNING("Warnings:"))
            for warning in report.warnings:
                self.stdout.write(f"- {warning}")
