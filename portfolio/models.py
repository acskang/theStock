from django.db import models


class Transaction(models.Model):
    TRADE_CHOICES = [
        ('매수', '매수'),
        ('매도', '매도'),
    ]

    trade_type = models.CharField('매매구분', max_length=10, choices=TRADE_CHOICES)
    stock_name = models.CharField('종목', max_length=100, db_index=True)
    year = models.IntegerField('년', db_index=True)
    month = models.IntegerField('월', db_index=True)
    day = models.IntegerField('일', db_index=True)
    hour = models.IntegerField('시')
    minute = models.IntegerField('분')
    quantity = models.IntegerField('수량(주)')
    unit_price = models.IntegerField('단가(원)')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-month', '-day', '-hour', '-minute', '-id']

    def __str__(self):
        return f'{self.trade_type} {self.stock_name} {self.quantity}주 @ {self.unit_price}'

    @property
    def total_amount(self):
        return self.quantity * self.unit_price


class StockSymbol(models.Model):
    stock_name = models.CharField('종목', max_length=100, unique=True)
    ticker = models.CharField('야후 티커', max_length=20, help_text='예: 035720.KS')
    note = models.CharField('메모', max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['stock_name']

    def __str__(self):
        return f'{self.stock_name} -> {self.ticker}'
