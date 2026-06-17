from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.http import JsonResponse
from django.shortcuts import redirect, render, resolve_url
from django.views.decorators.http import require_http_methods

from .cookies import clear_thepeach_auth_cookies
from .forms import LocalLoginForm, LocalSignupForm
from .session import clear_thepeach_session


def _is_json_request(request) -> bool:
    requested_with = request.headers.get("X-Requested-With", "")
    accept = request.headers.get("Accept", "")
    return requested_with == "XMLHttpRequest" or "application/json" in accept


def _first_form_error(form, default: str) -> str:
    non_field_errors = form.non_field_errors()
    if non_field_errors:
        return str(non_field_errors[0])
    for field_errors in form.errors.values():
        if field_errors:
            return str(field_errors[0])
    return default


def _json_error(message: str, *, status: int = 400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _json_success(*, redirect_url: str, message: str = ""):
    return JsonResponse({"ok": True, "redirect_url": redirect_url, "message": message})


def _signup_url(next_url: str) -> str:
    return f"{resolve_url('signup')}?{urlencode({'next': next_url})}"


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(resolve_url(request.GET.get("next") or settings.LOGIN_REDIRECT_URL))

    form = LocalLoginForm(request, request.POST or None)
    next_url = resolve_url(request.GET.get("next") or request.POST.get("next") or settings.LOGIN_REDIRECT_URL)
    error_message = ""

    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user(), backend="django.contrib.auth.backends.ModelBackend")
        response = _json_success(redirect_url=next_url, message="로그인되었습니다.") if _is_json_request(request) else redirect(next_url)
        clear_thepeach_auth_cookies(response)
        clear_thepeach_session(request)
        return response
    if request.method == "POST":
        error_message = _first_form_error(form, "입력값을 확인해주세요.")
        if _is_json_request(request):
            return _json_error(error_message)

    return render(
        request,
        "registration/login.html",
        {
            "form": form,
            "next": next_url,
            "auth_error_message": error_message,
            "signup_url": _signup_url(next_url),
        },
    )


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect(resolve_url(request.GET.get("next") or settings.LOGIN_REDIRECT_URL))

    form = LocalSignupForm(request.POST or None)
    next_url = resolve_url(request.GET.get("next") or request.POST.get("next") or settings.LOGIN_REDIRECT_URL)
    error_message = ""

    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        response = _json_success(redirect_url=next_url, message="회원가입이 완료되었습니다.") if _is_json_request(request) else redirect(next_url)
        clear_thepeach_auth_cookies(response)
        clear_thepeach_session(request)
        return response
    if request.method == "POST":
        error_message = _first_form_error(form, "입력값을 확인해주세요.")
        if _is_json_request(request):
            return _json_error(error_message)

    return render(
        request,
        "registration/signup.html",
        {
            "form": form,
            "next": next_url,
            "auth_error_message": error_message,
        },
    )


@require_http_methods(["POST"])
def logout_view(request):
    clear_thepeach_session(request)
    auth_logout(request)
    redirect_url = resolve_url(request.POST.get("next") or settings.LOGOUT_REDIRECT_URL)
    response = _json_success(redirect_url=redirect_url, message="로그아웃되었습니다.") if _is_json_request(request) else redirect(redirect_url)
    clear_thepeach_auth_cookies(response)
    return response
