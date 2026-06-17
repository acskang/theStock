from django.core.management.base import BaseCommand, CommandError
import pandas as pd
from portfolio.services import import_transactions_from_dataframe


class Command(BaseCommand):
    help = 'CSV 파일을 불러와 거래내역을 저장합니다.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)

    def handle(self, *args, **options):
        path = options['csv_path']
        try:
            df = pd.read_csv(path)
            count = import_transactions_from_dataframe(df)
        except Exception as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f'Imported {count} rows'))
