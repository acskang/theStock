from __future__ import annotations

from django import forms
from django.core.validators import RegexValidator

from integrations.services.toss_holdings_apply import APPLY_CONFIRM_TEXT


MAX_CREDENTIAL_LENGTH = 512
SYMBOL_VALIDATOR = RegexValidator(
    regex=r"^[A-Za-z0-9.\-]+$",
    message="종목 입력값을 확인해 주세요.",
)


class TossCredentialForm(forms.Form):
    client_id = forms.CharField(
        label="Toss Open API client_id",
        required=True,
        strip=True,
        max_length=MAX_CREDENTIAL_LENGTH,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "client_id",
            }
        ),
    )
    client_secret = forms.CharField(
        label="Toss Open API client_secret",
        required=True,
        strip=True,
        max_length=MAX_CREDENTIAL_LENGTH,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "client_secret",
            },
            render_value=False,
        ),
    )
    confirm_terms_ack = forms.BooleanField(
        label="토스증권 Open API credential을 theStock에 암호화 저장하는 것에 동의합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_client_secret(self) -> str:
        # If Toss ever treats surrounding whitespace as significant, revisit this form policy.
        value = self.cleaned_data["client_secret"].strip()
        if not value:
            raise forms.ValidationError("client_secret을 입력해 주세요.")
        return value


class RevealCredentialForm(forms.Form):
    password = forms.CharField(
        label="비밀번호 재확인",
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "현재 비밀번호",
            },
            render_value=False,
        ),
    )


class ConfirmActionForm(forms.Form):
    confirm = forms.BooleanField(
        label="이 작업을 확인합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TossCredentialVerificationForm(forms.Form):
    confirm = forms.BooleanField(
        label="저장된 Toss credential로 read-only 연결 확인을 실행합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TossAccountSelectionForm(forms.Form):
    selected_account_hash = forms.CharField(
        label="대표 계좌",
        required=True,
        max_length=64,
        validators=[
            RegexValidator(
                regex=r"^[0-9a-f]{64}$",
                message="선택한 계좌 값을 확인해 주세요.",
            )
        ],
        widget=forms.RadioSelect,
    )
    confirm = forms.BooleanField(
        label="선택한 계좌를 대표 계좌로 연결합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TossHoldingsDryRunForm(forms.Form):
    symbol = forms.CharField(
        label="종목",
        required=False,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        help_text="비워두면 전체 보유종목 기준으로 dry-run plan을 계산합니다.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )
    confirm = forms.BooleanField(
        label="실제 DB 반영 없이 보유종목 동기화 미리보기를 실행합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TossHoldingsApplyForm(forms.Form):
    confirmation_token = forms.CharField(
        required=True,
        widget=forms.HiddenInput(),
    )
    password = forms.CharField(
        label="현재 비밀번호",
        required=True,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "현재 비밀번호",
            },
            render_value=False,
        ),
    )
    confirmation_text = forms.CharField(
        label="확인을 위해 '반영'을 입력하세요.",
        required=True,
        strip=True,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "placeholder": APPLY_CONFIRM_TEXT,
            }
        ),
    )
    confirm = forms.BooleanField(
        label="create/update만 실제 UserHolding에 반영하며 삭제 후보는 삭제하지 않음을 확인했습니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_confirmation_text(self) -> str:
        if self.cleaned_data["confirmation_text"] != APPLY_CONFIRM_TEXT:
            raise forms.ValidationError("확인 문구를 정확히 입력해 주세요.")
        return APPLY_CONFIRM_TEXT


class TossOrderHistoryFilterForm(forms.Form):
    STATUS_CHOICES = (
        ("CLOSED", "종료됨"),
        ("OPEN", "진행 중"),
    )
    LIMIT_CHOICES = (
        ("20", "20"),
        ("50", "50"),
        ("100", "100"),
    )

    status = forms.ChoiceField(
        label="주문 상태",
        choices=STATUS_CHOICES,
        initial="CLOSED",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    symbol = forms.CharField(
        label="종목",
        required=False,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )
    from_date = forms.DateField(
        label="시작일",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    to_date = forms.DateField(
        label="종료일",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    limit = forms.ChoiceField(
        label="페이지 크기",
        choices=LIMIT_CHOICES,
        initial="20",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    cursor = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def clean(self) -> dict:
        cleaned = super().clean()
        from_date = cleaned.get("from_date")
        to_date = cleaned.get("to_date")
        if from_date and to_date and from_date > to_date:
            raise forms.ValidationError("조회 시작일은 종료일보다 늦을 수 없습니다.")
        if cleaned.get("status") == "OPEN":
            cleaned["cursor"] = ""
        return cleaned


class TossDashboardHoldingsForm(forms.Form):
    symbol = forms.CharField(
        label="종목",
        required=False,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )


class TossDashboardOrdersForm(forms.Form):
    STATUS_CHOICES = (
        ("CLOSED", "종료됨"),
        ("OPEN", "진행 중"),
    )
    LIMIT_CHOICES = (
        ("5", "5"),
        ("10", "10"),
        ("20", "20"),
    )

    status = forms.ChoiceField(
        label="주문 상태",
        choices=STATUS_CHOICES,
        initial="CLOSED",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    limit = forms.ChoiceField(
        label="조회 건수",
        choices=LIMIT_CHOICES,
        initial="10",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    symbol = forms.CharField(
        label="종목",
        required=False,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )


class TossAccountTradingInfoForm(forms.Form):
    confirm = forms.BooleanField(
        label="매수 가능 금액과 매매 수수료를 조회합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TossSellableQuantityForm(forms.Form):
    symbol = forms.CharField(
        label="종목",
        required=True,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "autocapitalize": "none",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )
    confirm = forms.BooleanField(
        label="선택한 종목의 매도 가능 수량을 조회합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class LocalStockSearchForm(forms.Form):
    query = forms.CharField(
        label="종목명",
        required=True,
        strip=True,
        max_length=80,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "placeholder": "삼성전자, 005930, AAPL",
            }
        ),
    )


class TossStockQuotesForm(forms.Form):
    symbols = forms.CharField(
        label="종목",
        required=True,
        strip=True,
        max_length=700,
        help_text="종목 검색 결과에서 선택하거나 symbol을 쉼표로 구분해 최대 20개까지 입력하세요.",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "rows": 2,
                "placeholder": "005930,AAPL,MSFT",
            }
        ),
    )


class TossSymbolDetailForm(forms.Form):
    TRADES_COUNT_CHOICES = (("10", "10"), ("20", "20"), ("50", "50"))

    symbol = forms.CharField(
        label="종목",
        required=True,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )
    trades_count = forms.ChoiceField(
        label="최근 체결 건수",
        choices=TRADES_COUNT_CHOICES,
        initial="20",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class TossCandleForm(forms.Form):
    INTERVAL_CHOICES = (("1d", "일봉"), ("1m", "1분봉"))
    COUNT_CHOICES = (("20", "20"), ("50", "50"), ("100", "100"), ("200", "200"))

    symbol = forms.CharField(
        label="종목",
        required=True,
        strip=True,
        max_length=32,
        validators=[SYMBOL_VALIDATOR],
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "off",
                "spellcheck": "false",
                "placeholder": "005930 또는 AAPL",
            }
        ),
    )
    interval = forms.ChoiceField(
        label="간격",
        choices=INTERVAL_CHOICES,
        initial="1d",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    count = forms.ChoiceField(
        label="개수",
        choices=COUNT_CHOICES,
        initial="50",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    adjusted = forms.BooleanField(
        label="수정주가 적용",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    before = forms.CharField(required=False, widget=forms.HiddenInput())


class TossExchangeRateForm(forms.Form):
    confirm = forms.BooleanField(
        label="현재 USD/KRW 참고 환율을 조회합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TossTradeSyncForm(forms.Form):
    MODE_CHOICES = (
        ("initial", "최초 전체 동기화"),
        ("incremental", "증분 동기화"),
    )

    mode = forms.ChoiceField(choices=MODE_CHOICES, widget=forms.HiddenInput())
    confirm = forms.BooleanField(
        label="Toss 체결 거래를 theStock 거래 DB에 등록하는 것을 확인합니다.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, mode: str = "incremental", **kwargs):
        initial = kwargs.pop("initial", {}) or {}
        initial.setdefault("mode", mode)
        super().__init__(*args, initial=initial, **kwargs)
        self.fields["mode"].initial = mode
        if mode == "initial":
            self.fields["confirm"].label = "지금까지의 모든 체결 거래를 가져와 거래 DB에 등록합니다."
        else:
            self.fields["confirm"].label = "마지막 성공 동기화 이후의 체결 거래를 가져옵니다."
