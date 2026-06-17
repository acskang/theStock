from django.core.management.base import BaseCommand
from portfolio.services import seed_default_symbols


class Command(BaseCommand):
    help = '기본 종목명-티커 매핑을 넣습니다.'

    def handle(self, *args, **kwargs):
        seed_default_symbols()
        self.stdout.write(self.style.SUCCESS('기본 티커 매핑 완료'))
