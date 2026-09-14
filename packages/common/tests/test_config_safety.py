import pytest

from common.config import Settings

pytestmark = pytest.mark.unit


def test_dev_environment_never_raises_even_with_default_secrets():
    settings = Settings(environment="dev")
    settings.require_safe_for_production()  # must not raise


def test_production_with_default_secret_key_raises():
    settings = Settings(environment="production", object_store_secret_key="a-real-secret")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.require_safe_for_production()


def test_production_with_default_object_store_secret_raises():
    settings = Settings(environment="production", secret_key="a-real-random-secret")
    with pytest.raises(RuntimeError, match="OBJECT_STORE_SECRET_KEY"):
        settings.require_safe_for_production()


def test_production_with_real_secrets_does_not_raise():
    settings = Settings(
        environment="production", secret_key="a-real-random-secret", object_store_secret_key="another-real-secret"
    )
    settings.require_safe_for_production()  # must not raise
