import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured


def get_env_var(var_name, default=None, required=True):
    value = os.environ.get(var_name, default)
    if required and value is None:
        raise ImproperlyConfigured(f"Missing required environment variable: {var_name}")
    return value


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = get_env_var('DJANGO_SECURE_STRING')

DOMAIN_NAME = get_env_var("DOMAIN_NAME", default="localhost", required=False)
WWW_DOMAIN_NAME = f"www.{DOMAIN_NAME}" if DOMAIN_NAME and "." in DOMAIN_NAME else ""
HTTPS_DOMAIN_NAME = f"https://{DOMAIN_NAME}" if DOMAIN_NAME and "." in DOMAIN_NAME else ""
HTTPS_WWW_DOMAIN_NAME = f"https://{WWW_DOMAIN_NAME}" if WWW_DOMAIN_NAME else ""
APP_NAME = get_env_var("APP_NAME", default="kjuu", required=False)
DATABASE_URL = get_env_var(
    "DATABASE_URL",
    default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    required=False,
)

DEBUG = os.environ.get("DEBUG", "False").lower() in {"1", "true", "yes"}

ALLOWED_HOSTS = [
    host for host in {DOMAIN_NAME, WWW_DOMAIN_NAME, "localhost", "127.0.0.1"} if host
]

CSRF_TRUSTED_ORIGINS = [origin for origin in [HTTPS_DOMAIN_NAME, HTTPS_WWW_DOMAIN_NAME] if origin]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'queueapp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = "kjuu.urls"

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = "kjuu.wsgi.application"


DATABASES = {
    "default": dj_database_url.config(
        default=DATABASE_URL
    )
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    db_test = DATABASES["default"].setdefault("TEST", {})
    # template1 may become unusable after host libc collation upgrades.
    db_test.setdefault("TEMPLATE", os.environ.get("DB_TEST_TEMPLATE", "template0"))


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LOG_DIR = BASE_DIR / 'logs'
os.makedirs(LOG_DIR, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} ({filename}:{lineno}) - {message}',
            'style': '{',
        },
    },

    'handlers': {
        'django_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'django.log',
            'maxBytes': 10 * 1024 * 1024, 
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },

    'loggers': {
        'django': {
            'handlers': ['django_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['django_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'queueapp': {
            'handlers': ['django_file'],
            'level': 'INFO',
            'propagate': False,
        },
        '': {
            'handlers': ['django_file'],  # root logger: catches everything else
            'level': 'DEBUG',
        },
    },
}

LANGUAGE_CODE = 'sk'
LANGUAGES = [
    ("sk", "Slovak"),
    ("en", "English"),
]
LOCALE_PATHS = [
    BASE_DIR / "locale",
]

TIME_ZONE = 'Europe/Bratislava'

USE_I18N = True

USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

LOGIN_URL = '/login/'

SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 year in seconds
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
