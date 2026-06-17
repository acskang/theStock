from django import forms
from django.contrib.auth import authenticate, get_user_model

from .models import UserProfile


class LocalLoginForm(forms.Form):
    username = forms.CharField(label="사용자 이름", max_length=150)
    password = forms.CharField(label="비밀번호", strip=False, widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        password = cleaned_data.get("password")
        if username and password:
            self.user = authenticate(self.request, username=username, password=password)
            if self.user is None:
                raise forms.ValidationError("사용자 이름 또는 비밀번호를 확인해주세요.")
            if not self.user.is_active:
                raise forms.ValidationError("비활성화된 계정입니다.")
        return cleaned_data

    def get_user(self):
        return self.user


class LocalSignupForm(forms.Form):
    username = forms.CharField(label="사용자 이름", max_length=150)
    full_name = forms.CharField(label="이름", max_length=255)
    smartphone_number = forms.CharField(label="스마트폰 번호", max_length=20)
    password = forms.CharField(label="비밀번호", strip=False, min_length=8, widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="비밀번호 확인", strip=False, widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("이미 사용 중인 사용자 이름입니다.")
        return username

    def clean_smartphone_number(self):
        value = str(self.cleaned_data["smartphone_number"] or "").strip()
        normalized = value.replace("-", "").replace(" ", "")
        if not normalized.isdigit() or not normalized.startswith("01") or len(normalized) not in {10, 11}:
            raise forms.ValidationError("스마트폰 번호를 정확히 입력해주세요.")
        return normalized

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "비밀번호가 일치하지 않습니다.")
        return cleaned_data

    def save(self):
        username = self.cleaned_data["username"]
        full_name = self.cleaned_data["full_name"].strip()
        first_name, _, last_name = full_name.partition(" ")
        User = get_user_model()
        user = User.objects.create_user(
            username=username,
            email="",
            password=self.cleaned_data["password"],
            first_name=first_name,
            last_name=last_name,
        )
        UserProfile.objects.create(user=user, smartphone_number=self.cleaned_data["smartphone_number"])
        return user


ThePeachLoginForm = LocalLoginForm
ThePeachSignupForm = LocalSignupForm
