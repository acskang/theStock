import os
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _load_project_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


_load_project_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    return str(os.environ.get(name, str(default))).lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in str(os.environ.get(name, default)).split(",") if item.strip()]


def _resolve_thepeach_base_url(name: str, default: str) -> str:
    base_url = str(os.environ.get(name, default)).rstrip("/")
    origin_base_url = str(os.environ.get("THEPEACH_ORIGIN_BASE_URL", "http://127.0.0.1")).rstrip("/")
    upstream_host = str(os.environ.get("THEPEACH_UPSTREAM_HOST_HEADER", "peach.thesysm.com")).strip()
    parsed = urlparse(base_url)
    if (
        not DEBUG
        and upstream_host
        and parsed.scheme in {"http", "https"}
        and parsed.hostname == upstream_host
    ):
        return origin_base_url
    return base_url


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "platform_auth",
    "rest_framework",
    "django_filters",
    "stocks",
    "holdings",
    "marketdata",
    "indicators",
    "decisions",
    "portfolio",
    "data_pipeline",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "stock_service.middleware.RequestLogContextMiddleware",
    "stock_service.middleware.AuthenticationGateMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "stock_service.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "stock_service.wsgi.application"
ASGI_APPLICATION = "stock_service.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "portfolio" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LEGACY_PORTFOLIO_USERNAME = os.environ.get("LEGACY_PORTFOLIO_USERNAME", "demo")
OPENDART_API_KEY = os.environ.get("OPENDART_API_KEY", "")
DATA_PIPELINE_PROVIDER = os.environ.get("DATA_PIPELINE_PROVIDER", "auto")
TOSS_INVEST_PROVIDER_ENABLED = _env_bool("TOSS_INVEST_PROVIDER_ENABLED", False)
TOSS_INVEST_BASE_URL = os.environ.get("TOSS_INVEST_BASE_URL", "https://openapi.tossinvest.com").rstrip("/")
TOSS_INVEST_TOKEN_URL = os.environ.get("TOSS_INVEST_TOKEN_URL", "")
TOSS_INVEST_CLIENT_ID = os.environ.get("TOSS_INVEST_CLIENT_ID", "")
TOSS_INVEST_CLIENT_SECRET = os.environ.get("TOSS_INVEST_CLIENT_SECRET", "")
TOSS_INVEST_ACCOUNT_ID = os.environ.get("TOSS_INVEST_ACCOUNT_ID", "")
TOSS_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("TOSS_REQUEST_TIMEOUT_SECONDS", "10"))
TOSS_MAX_RETRIES = int(os.environ.get("TOSS_MAX_RETRIES", "2"))
TOSS_RATE_LIMIT_PER_MINUTE = int(os.environ.get("TOSS_RATE_LIMIT_PER_MINUTE", "60"))
TOSS_ORDER_EXECUTION_ENABLED = _env_bool("TOSS_ORDER_EXECUTION_ENABLED", False)
APP_VERSION = os.environ.get("APP_VERSION", "dev")
APP_BUILD_SHA = os.environ.get("APP_BUILD_SHA", "-")
READINESS_CHECK_MIGRATIONS = os.environ.get("READINESS_CHECK_MIGRATIONS", "1").lower() not in {
    "0",
    "false",
    "no",
}
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = os.environ.get("X_FRAME_OPTIONS", "DENY")
SECURE_REFERRER_POLICY = os.environ.get("SECURE_REFERRER_POLICY", "same-origin")

THEPEACH_AUTH_BASE_URL = _resolve_thepeach_base_url("THEPEACH_AUTH_BASE_URL", "http://127.0.0.1")
THEPEACH_LOGIN_BASE_URL = _resolve_thepeach_base_url("THEPEACH_LOGIN_BASE_URL", THEPEACH_AUTH_BASE_URL)
THEPEACH_PUBLIC_BASE_URL = str(os.environ.get("THEPEACH_PUBLIC_BASE_URL", "https://peach.thesysm.com")).rstrip("/")
THEPEACH_PUBLIC_SIGNUP_URL = str(os.environ.get("THEPEACH_PUBLIC_SIGNUP_URL", "")).strip()
THEPEACH_PUBLIC_LOGIN_URL = str(os.environ.get("THEPEACH_PUBLIC_LOGIN_URL", "")).strip()
THEPEACH_PUBLIC_LOGOUT_URL = str(os.environ.get("THEPEACH_PUBLIC_LOGOUT_URL", "")).strip()
THEPEACH_UPSTREAM_HOST_HEADER = os.environ.get("THEPEACH_UPSTREAM_HOST_HEADER", "peach.thesysm.com").strip()
THEPEACH_SSO_ACCESS_COOKIE_NAME = os.environ.get("THEPEACH_SSO_ACCESS_COOKIE_NAME", "thepeach_sso_access")
THEPEACH_SSO_REFRESH_COOKIE_NAME = os.environ.get("THEPEACH_SSO_REFRESH_COOKIE_NAME", "thepeach_sso_refresh")
THEPEACH_SSO_COOKIE_DOMAIN = os.environ.get("THEPEACH_SSO_COOKIE_DOMAIN", ".thesysm.com")
THEPEACH_SSO_COOKIE_PATH = os.environ.get("THEPEACH_SSO_COOKIE_PATH", "/")
THEPEACH_SSO_COOKIE_SAMESITE = os.environ.get("THEPEACH_SSO_COOKIE_SAMESITE", "Lax")
THEPEACH_SSO_COOKIE_SECURE = _env_bool("THEPEACH_SSO_COOKIE_SECURE", False)
THEPEACH_SIGNUP_PATH = os.environ.get("THEPEACH_SIGNUP_PATH", "/api/v1/auth/signup/")
THEPEACH_LOGIN_PATH = os.environ.get("THEPEACH_LOGIN_PATH", "/api/v1/auth/login/")
THEPEACH_REFRESH_PATH = os.environ.get("THEPEACH_REFRESH_PATH", "/api/v1/auth/token/refresh/")
THEPEACH_LOGOUT_PATH = os.environ.get("THEPEACH_LOGOUT_PATH", "/api/v1/auth/logout/")
THEPEACH_PROFILE_PATH = os.environ.get("THEPEACH_PROFILE_PATH", "/api/v1/auth/me/")
THEPEACH_AUTH_TIMEOUT = int(os.environ.get("THEPEACH_AUTH_TIMEOUT", "10"))

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "consulting_holding_list"
LOGOUT_REDIRECT_URL = "dashboard"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "rest_framework.schemas.openapi.AutoSchema",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {
            "()": "stock_service.logging_context.RequestContextFilter",
        },
    },
    "formatters": {
        "structured": {
            "format": (
                "%(asctime)s level=%(levelname)s logger=%(name)s "
                "request_id=%(request_id)s user_id=%(user_id)s method=%(method)s path=%(path)s "
                "event=%(event)s holding_id=%(holding_id)s stock_code=%(stock_code)s "
                "command=%(command)s source=%(source)s status_code=%(status_code)s "
                "duration_ms=%(duration_ms)s error_type=%(error_type)s message=%(message)s"
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "filters": ["request_context"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "holdings.views": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "decisions.services.averaging_decision_service": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "decisions.services.probability_service": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "decisions.services.consulting_service": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "stock_service.middleware": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "platform_auth": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "numexpr.utils": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
