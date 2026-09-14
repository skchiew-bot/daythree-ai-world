import jwt
import pytest

from common.config import Settings
from contracts.ids import new_id

from api.dependencies.auth import create_access_token, hash_password, verify_password

pytestmark = pytest.mark.unit


def test_password_hash_roundtrip():
    password_hash = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_password_hash_is_not_the_plaintext():
    password_hash = hash_password("hunter2")
    assert password_hash != "hunter2"
    assert password_hash.startswith("$2b$")


def test_access_token_roundtrip_carries_tenant_and_role():
    settings = Settings(secret_key="test-secret", jwt_algorithm="HS256", jwt_expire_minutes=60)
    user_id, tenant_id = new_id(), new_id()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="tenant_admin", settings=settings)
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "tenant_admin"


def test_token_signed_with_a_different_secret_is_rejected():
    settings = Settings(secret_key="secret-a", jwt_algorithm="HS256", jwt_expire_minutes=60)
    token = create_access_token(user_id=new_id(), tenant_id=new_id(), role="viewer", settings=settings)

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "secret-b", algorithms=["HS256"])
