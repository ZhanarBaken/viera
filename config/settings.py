from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["https://*.railway.app"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "automation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3")
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_USE_FINDERS = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Almaty"
USE_I18N = True
USE_TZ = True

# Celery
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_TRACK_STARTED = True

# Integrations
AMOCRM_DOMAIN = env("AMOCRM_DOMAIN")
AMOCRM_ACCESS_TOKEN = env("AMOCRM_ACCESS_TOKEN")
AMOCRM_PIPELINE_ID = env.int("AMOCRM_PIPELINE_ID")
AMOCRM_STAGE_DRIP_ID = env.int("AMOCRM_STAGE_DRIP_ID")
AMOCRM_STAGE_HUMAN_ID = env.int("AMOCRM_STAGE_HUMAN_ID")
# Этапы, из которых бот имеет право переводить лид в Дожим бот
AMOCRM_ALLOWED_STAGE_IDS = set(env.list("AMOCRM_ALLOWED_STAGE_IDS", default=["142"]))

WAZZUP_TOKEN = env("WAZZUP_TOKEN")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

# DRY_RUN=True → все операции только логируются
# DRY_RUN_EXCEPTIONS — номера телефонов (только цифры), для которых боевой режим даже при DRY_RUN
DRY_RUN = env.bool("DRY_RUN", default=False)
DRY_RUN_EXCEPTIONS = {"".join(c for c in p if c.isdigit()) for p in env.list("DRY_RUN_EXCEPTIONS", default=[])}


