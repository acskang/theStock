from django import forms
from .models import StockSymbol, Transaction


class CSVUploadForm(forms.Form):
    csv_file = forms.FileField(label='CSV 파일')


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['trade_type', 'stock_name', 'year', 'month', 'day', 'hour', 'minute', 'quantity', 'unit_price']
        widgets = {
            'trade_type': forms.Select(attrs={'class': 'form-select'}),
            'stock_name': forms.TextInput(attrs={'class': 'form-control'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'month': forms.NumberInput(attrs={'class': 'form-control'}),
            'day': forms.NumberInput(attrs={'class': 'form-control'}),
            'hour': forms.NumberInput(attrs={'class': 'form-control'}),
            'minute': forms.NumberInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class StockSymbolForm(forms.ModelForm):
    class Meta:
        model = StockSymbol
        fields = ['stock_name', 'ticker', 'note']
        widgets = {
            'stock_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 삼성전자'}),
            'ticker': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 005930.KS'}),
            'note': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 코스피(.KS), 코스닥(.KQ)'}),
        }


class SymbolResolveForm(forms.Form):
    stock_name = forms.CharField(widget=forms.HiddenInput())
    ticker = forms.CharField(
        label='야후 티커',
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '예: 035720.KS'})
    )
    note = forms.CharField(
        label='메모',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '선택 입력'})
    )
