#this projet build by safouane02
#who is safouane02 ?
#old account of git hub 


import os
import sys
import warnings
from pathlib import Path
from urllib.parse import quote, urlparse

from django.core.exceptions import ImproperlyConfigured


def load_dotenv(dotenv_path):
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_int(name, default=0):
    value = os.getenv(name)
    if value is None or value == "":
        return int(default)
    return int(value)


def with_trailing_slash(value):
    value = (value or "").strip()
    if not value:
        return "/"
    return value.rstrip("/") + "/"


def build_redis_url():
    explicit_url = os.getenv("REDIS_URL", "").strip()
    if explicit_url:
        return explicit_url

    host = os.getenv("REDIS_HOST", "").strip()
    if not host:
        return ""

    scheme = os.getenv("REDIS_SCHEME", "redis").strip() or "redis"
    port = os.getenv("REDIS_PORT", "6379").strip() or "6379"
    db = os.getenv("REDIS_DB", "0").strip() or "0"
    username = os.getenv("REDIS_USERNAME", "").strip()
    password = os.getenv("REDIS_PASSWORD", "").strip()

    auth = ""
    if username and password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    elif password:
        auth = f":{quote(password, safe='')}@"
    elif username:
        auth = f"{quote(username, safe='')}@"

    return f"{scheme}://{auth}{host}:{port}/{db}"


def build_postgres_options():
    options = {}

    if env_bool("DB_USE_POOL", False):
        try:
            import psycopg_pool  # noqa: F401
        except ImportError:
            pass
        else:
            min_size = max(1, env_int("DB_POOL_MIN_SIZE", 1))
            max_size = max(min_size, env_int("DB_POOL_MAX_SIZE", 8))
            options["pool"] = {
                "min_size": min_size,
                "max_size": max_size,
                "timeout": env_int("DB_POOL_TIMEOUT", 30),
            }

    return options


def resolved_conn_max_age(engine, options):
    conn_max_age = env_int("DB_CONN_MAX_AGE", 0)
    if engine == "django.db.backends.postgresql" and options.get("pool") and conn_max_age != 0:
        warnings.warn(
            "DB_CONN_MAX_AGE was set while PostgreSQL pooling is enabled. "
            "Django pooling requires CONN_MAX_AGE=0, so it has been forced to 0.",
            RuntimeWarning,
        )
        return 0
    return conn_max_age


def build_database_config(base_dir):
    postgres_options = build_postgres_options()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        parsed = urlparse(database_url)
        scheme = parsed.scheme.lower()
        engines = {
            "postgres": "django.db.backends.postgresql",
            "postgresql": "django.db.backends.postgresql",
            "pgsql": "django.db.backends.postgresql",
            "sqlite": "django.db.backends.sqlite3",
        }
        engine = engines.get(scheme)
        if not engine:
            raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {scheme}")
        if engine == "django.db.backends.sqlite3":
            db_name = parsed.path.lstrip("/") or "db.sqlite3"
            name = base_dir / db_name
        else:
            name = parsed.path.lstrip("/")
        conn_max_age = resolved_conn_max_age(engine, postgres_options if engine == "django.db.backends.postgresql" else {})
        return {
            "ENGINE": engine,
            "NAME": str(name),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": conn_max_age,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": postgres_options if engine == "django.db.backends.postgresql" else {},
        }

    db_engine = os.getenv("DB_ENGINE", "sqlite").strip().lower()
    if db_engine in {"sqlite", "sqlite3"}:
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": base_dir / os.getenv("DB_NAME", "db.sqlite3"),
        }
    if db_engine in {"postgres", "postgresql"}:
        conn_max_age = resolved_conn_max_age("django.db.backends.postgresql", postgres_options)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "escrow_project"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": conn_max_age,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": postgres_options,
        }
    raise ImproperlyConfigured(f"Unsupported DB_ENGINE value: {db_engine}")


def validate_production_runtime(
    *,
    debug,
    database_config,
    redis_url,
    celery_broker_url,
    site_url,
    stripe_public_key,
    stripe_secret_key,
    stripe_webhook_secret,
    allow_test_payment_keys_in_production,
    withdrawal_enabled,
    allow_manual_withdrawals_in_production,
):
    if debug:
        return

    if database_config.get("ENGINE") == "django.db.backends.sqlite3":
        raise ImproperlyConfigured(
            "Refusing to start with SQLite while DJANGO_DEBUG=False. Configure PostgreSQL for production."
        )

    if not redis_url:
        raise ImproperlyConfigured(
            "Set REDIS_URL or REDIS_HOST in production. InMemoryChannelLayer is not allowed while DJANGO_DEBUG=False."
        )

    if not celery_broker_url:
        raise ImproperlyConfigured(
            "Set CELERY_BROKER_URL or REDIS_URL in production so background jobs can run safely."
        )

    if not site_url:
        raise ImproperlyConfigured("Set SITE_URL in production.")

    stripe_values = [stripe_public_key, stripe_secret_key, stripe_webhook_secret]
    if any(stripe_values) and not all(stripe_values):
        raise ImproperlyConfigured(
            "Set STRIPE_PUBLIC_KEY, STRIPE_SECRET_KEY, and STRIPE_WEBHOOK_SECRET together."
        )

    if (
        stripe_public_key == "pk_test_..."
        or stripe_secret_key == "sk_test_..."
        or stripe_webhook_secret == "whsec_..."
    ):
        raise ImproperlyConfigured(
            "Replace Stripe placeholder values before starting with DJANGO_DEBUG=False."
        )

    if (
        withdrawal_enabled
        and not allow_manual_withdrawals_in_production
    ):
        raise ImproperlyConfigured(
            "Refusing to enable withdrawals while DJANGO_DEBUG=False without "
            "ALLOW_MANUAL_WITHDRAWALS_IN_PRODUCTION=True."
        )


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-this-key-in-production-please!!")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DJANGO_DEBUG", True)

if not DEBUG and SECRET_KEY == "django-insecure-change-this-key-in-production-please!!":
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in production.")

SITE_URL = os.getenv("SITE_URL", "").strip().rstrip("/")
site_url_host = ""
site_url_origin = ""
if SITE_URL:
    parsed_site_url = urlparse(SITE_URL)
    site_url_host = parsed_site_url.hostname or ""
    if parsed_site_url.scheme and parsed_site_url.netloc:
        site_url_origin = f"{parsed_site_url.scheme}://{parsed_site_url.netloc}"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
if site_url_host:
    ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, site_url_host]))
ALLOW_NGROK_HOSTS = env_bool("DJANGO_ALLOW_NGROK_HOSTS", DEBUG)
extra_dev_hosts = ["localhost", "127.0.0.1"]
if ALLOW_NGROK_HOSTS:
    extra_dev_hosts.extend([".ngrok-free.dev", ".ngrok.io"])
ALLOWED_HOSTS = list(
    dict.fromkeys(
        [
            *ALLOWED_HOSTS,
            *extra_dev_hosts,
        ]
    )
)
if RUNNING_TESTS:
    ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, "testserver", "localhost", "127.0.0.1"]))
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "",
)
if site_url_origin:
    CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, site_url_origin]))
extra_csrf_origins = []
if ALLOW_NGROK_HOSTS:
    extra_csrf_origins.extend(["https://*.ngrok-free.dev", "https://*.ngrok.io"])
CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        [
            *CSRF_TRUSTED_ORIGINS,
            *extra_csrf_origins,
        ]
    )
)
USE_S3_STORAGE = env_bool("USE_S3_STORAGE", False)


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",  # Required by django-allauth
    
    # Third-party apps
    "channels",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "django_cleanup.apps.CleanupConfig",
    
    # Local apps
    "main.apps.MainConfig",
]

if USE_S3_STORAGE:
    INSTALLED_APPS.append("storages")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "main.middleware.SiteLanguageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.http.ConditionalGetMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",  # Required by django-allauth
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "main.middleware.SecurityHeadersMiddleware",
    "main.middleware.PerformanceHeadersMiddleware",
    "main.middleware.RateLimitMiddleware",
    "main.middleware.AdminProtectionMiddleware",
    "main.middleware.Custom404Middleware",
]

if not USE_S3_STORAGE:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "main.context_processors.site_language",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# Django Channels — InMemoryChannelLayer for development
# For production, switch to channels_redis.core.RedisChannelLayer
REDIS_URL = build_redis_url()
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

# -- Cache backend ---------------------------------------------------------
# Redis when configured (shared across workers, so rate limiting and any
# template/query caching actually work in production); local memory in dev.
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "dzhub",
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dzhub-dev",
        },
    }

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL).strip()
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL).strip()
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = os.getenv("CELERY_TIMEZONE", "").strip()
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env_int("CELERY_TASK_TIME_LIMIT", 300)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
if CELERY_BROKER_URL:
    CELERY_BEAT_SCHEDULE = {
        "close-expired-auctions-every-minute": {
            "task": "main.tasks.finalize_expired_auctions",
            "schedule": env_int("CELERY_AUCTION_SWEEP_SECONDS", 60),
        },
        "process-deal-deadlines-every-five-minutes": {
            "task": "main.tasks.process_deal_deadline_notifications",
            "schedule": env_int("CELERY_DEADLINE_SWEEP_SECONDS", 300),
        },
    }

# Database
DATABASES = {
    "default": build_database_config(BASE_DIR)
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "ar"
LANGUAGES = [
    ("ar", "Arabic"),
    ("en", "English"),
]
TIME_ZONE = "Africa/Algiers"
USE_I18N = True
USE_L10N = True
USE_TZ = True
if not CELERY_TIMEZONE:
    CELERY_TIMEZONE = TIME_ZONE

# Static files (CSS, JavaScript, Images)
STATIC_URL = with_trailing_slash(os.getenv("DJANGO_STATIC_URL", "/static/"))
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_ALLOW_ALL_ORIGINS = True
WHITENOISE_MAX_AGE = env_int("WHITENOISE_MAX_AGE", 31536000 if not DEBUG else 3600)
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG
MAINTENANCE_END_AT = os.getenv("MAINTENANCE_END_AT", "").strip()

# Media files
if USE_S3_STORAGE:
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "").strip()
    if not AWS_STORAGE_BUCKET_NAME:
        raise ImproperlyConfigured("Set AWS_STORAGE_BUCKET_NAME when USE_S3_STORAGE is enabled.")

    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "").strip()
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL", "").strip()
    AWS_S3_CUSTOM_DOMAIN = os.getenv("AWS_S3_CUSTOM_DOMAIN", "").strip()
    AWS_S3_ADDRESSING_STYLE = os.getenv("AWS_S3_ADDRESSING_STYLE", "auto").strip()
    AWS_LOCATION = os.getenv("AWS_LOCATION", "media").strip().strip("/")
    AWS_QUERYSTRING_AUTH = env_bool("AWS_QUERYSTRING_AUTH", True)
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False

    s3_options = {
        "bucket_name": AWS_STORAGE_BUCKET_NAME,
        "default_acl": AWS_DEFAULT_ACL,
        "file_overwrite": AWS_S3_FILE_OVERWRITE,
        "querystring_auth": AWS_QUERYSTRING_AUTH,
        "addressing_style": AWS_S3_ADDRESSING_STYLE,
    }
    if AWS_ACCESS_KEY_ID:
        s3_options["access_key"] = AWS_ACCESS_KEY_ID
    if AWS_SECRET_ACCESS_KEY:
        s3_options["secret_key"] = AWS_SECRET_ACCESS_KEY
    if AWS_S3_REGION_NAME:
        s3_options["region_name"] = AWS_S3_REGION_NAME
    if AWS_S3_ENDPOINT_URL:
        s3_options["endpoint_url"] = AWS_S3_ENDPOINT_URL
    if AWS_S3_CUSTOM_DOMAIN:
        s3_options["custom_domain"] = AWS_S3_CUSTOM_DOMAIN
    if AWS_LOCATION:
        s3_options["location"] = AWS_LOCATION

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": s3_options,
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

    media_prefix = f"{AWS_LOCATION}/" if AWS_LOCATION else ""
    explicit_media_url = os.getenv("AWS_MEDIA_URL", "").strip()
    if explicit_media_url:
        MEDIA_URL = explicit_media_url.rstrip("/") + "/"
    elif AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{media_prefix}"
    elif AWS_S3_ENDPOINT_URL:
        MEDIA_URL = f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/{media_prefix}"
    else:
        MEDIA_URL = f"https://{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com/{media_prefix}"
    MEDIA_ROOT = None
else:
    staticfiles_backend = os.getenv(
        "DJANGO_STATICFILES_STORAGE",
        "whitenoise.storage.CompressedStaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage",
    )
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": staticfiles_backend,
        },
    }
    MEDIA_URL = with_trailing_slash(os.getenv("DJANGO_MEDIA_URL", "/media/"))
    MEDIA_ROOT = BASE_DIR / "media"

# Authentication redirects
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "my_deals"
LOGOUT_REDIRECT_URL = "home"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "pk_test_...")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_...")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_...")
STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "usd").strip().lower() or "usd"
ALLOW_TEST_PAYMENT_KEYS_IN_PRODUCTION = env_bool("ALLOW_TEST_PAYMENT_KEYS_IN_PRODUCTION", False)

if (
    not DEBUG
    and not ALLOW_TEST_PAYMENT_KEYS_IN_PRODUCTION
    and (
        STRIPE_PUBLIC_KEY.startswith("pk_test_")
        or STRIPE_SECRET_KEY.startswith("sk_test_")
    )
):
    raise ImproperlyConfigured(
        "Refusing to start with Stripe test keys while DJANGO_DEBUG=False. "
        "Use live Stripe keys or explicitly set ALLOW_TEST_PAYMENT_KEYS_IN_PRODUCTION=True for staging."
    )

# ==================== django-allauth Configuration ====================
SITE_ID = env_int("DJANGO_SITE_ID", 1)

AUTHENTICATION_BACKENDS = [
    # Needed to login by username in Django admin, regardless of `allauth`
    'django.contrib.auth.backends.ModelBackend',
    
    # `allauth` specific authentication methods, such as login by e-mail
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Allauth settings (new format)
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'username*', 'password1*', 'password2*']
SILENCED_SYSTEM_CHECKS = ['account.W001']
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_ADAPTER = 'main.adapters.BrandedAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'allauth.socialaccount.adapter.DefaultSocialAccountAdapter'
SOCIALACCOUNT_FORMS = {'signup': 'main.forms.SimpleSocialSignupForm'}
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_AUTO_SIGNUP = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_QUERY_EMAIL = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[DZHub] "

# ==========================================
# ESCROW PLATFORM SETTINGS
# ==========================================
# النسبة المئوية المقتطعة كرسوم للمنصة من كل صفقة ناجحة (0.05 تعني 5%)
ESCROW_FEE_PERCENTAGE = 0.05
PLATFORM_OWNER_USERNAME = os.getenv("PLATFORM_OWNER_USERNAME", "").strip()

# هل ميزة السحب مفعلة؟ (معطلة افتراضياً حتى يتم ربط payout حقيقي)
WITHDRAWAL_ENABLED = env_bool("WITHDRAWAL_ENABLED", False)
ALLOW_MANUAL_WITHDRAWALS_IN_PRODUCTION = env_bool("ALLOW_MANUAL_WITHDRAWALS_IN_PRODUCTION", False)

validate_production_runtime(
    debug=DEBUG,
    database_config=DATABASES["default"],
    redis_url=REDIS_URL,
    celery_broker_url=CELERY_BROKER_URL,
    site_url=SITE_URL,
    stripe_public_key=STRIPE_PUBLIC_KEY,
    stripe_secret_key=STRIPE_SECRET_KEY,
    stripe_webhook_secret=STRIPE_WEBHOOK_SECRET,
    allow_test_payment_keys_in_production=ALLOW_TEST_PAYMENT_KEYS_IN_PRODUCTION,
    withdrawal_enabled=WITHDRAWAL_ENABLED,
    allow_manual_withdrawals_in_production=ALLOW_MANUAL_WITHDRAWALS_IN_PRODUCTION,
)

# Socialaccount providers
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': os.getenv('GOOGLE_CLIENT_ID', 'placeholder-google-client-id'),
            'secret': os.getenv('GOOGLE_CLIENT_SECRET', 'placeholder-google-client-secret'),
            'key': ''
        },
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        }
    }
}

# ==================== Email Configuration ====================
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 465))
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', EMAIL_PORT == 465)
EMAIL_USE_TLS = False if EMAIL_USE_SSL else env_bool('EMAIL_USE_TLS', True)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '').replace(' ', '').strip()
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'noreply@localhost')
EMAIL_TIMEOUT = env_int('EMAIL_TIMEOUT', 15)

if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Ensure HTTPS redirect URIs are generated when behind a proxy like Ngrok
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = os.getenv("DJANGO_SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.getenv("DJANGO_CSRF_COOKIE_SAMESITE", "Lax")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
if RUNNING_TESTS:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000 if not DEBUG else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = os.getenv("DJANGO_SECURE_REFERRER_POLICY", "same-origin")
SECURE_CROSS_ORIGIN_OPENER_POLICY = os.getenv(
    "DJANGO_SECURE_CROSS_ORIGIN_OPENER_POLICY",
    "same-origin",
)
