from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='StockSymbol',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stock_name', models.CharField(max_length=100, unique=True, verbose_name='종목')),
                ('ticker', models.CharField(help_text='예: 035720.KS', max_length=20, verbose_name='야후 티커')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='메모')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['stock_name']},
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trade_type', models.CharField(choices=[('매수', '매수'), ('매도', '매도')], max_length=10, verbose_name='매매구분')),
                ('stock_name', models.CharField(db_index=True, max_length=100, verbose_name='종목')),
                ('year', models.IntegerField(db_index=True, verbose_name='년')),
                ('month', models.IntegerField(db_index=True, verbose_name='월')),
                ('day', models.IntegerField(db_index=True, verbose_name='일')),
                ('hour', models.IntegerField(verbose_name='시')),
                ('minute', models.IntegerField(verbose_name='분')),
                ('quantity', models.IntegerField(verbose_name='수량(주)')),
                ('unit_price', models.IntegerField(verbose_name='단가(원)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-year', '-month', '-day', '-hour', '-minute', '-id']},
        ),
    ]
