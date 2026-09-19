"""Pure-domain tests for the `dtk_<key_id>_<secret>` wire format parser (T1-F15). No
DB/network needed -- `_parse_key` never touches the database.
"""
from __future__ import annotations

import uuid

import pytest

from api.dependencies.agent_runtime_auth import _parse_key

pytestmark = pytest.mark.unit


def test_parses_a_well_formed_key():
    key_id = uuid.uuid4()
    token = f"dtk_{key_id.hex}_abc-DEF_123"

    parsed = _parse_key(token)

    assert parsed == (key_id, "abc-DEF_123")


def test_secret_may_itself_contain_underscores_without_breaking_the_split():
    key_id = uuid.uuid4()
    secret = "has_several_underscores_in_it"
    token = f"dtk_{key_id.hex}_{secret}"

    parsed = _parse_key(token)

    assert parsed == (key_id, secret)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-key",
        "dtk_",
        "dtk_notahexkeyid_secret",
        f"dtk_{'a' * 31}_secret",  # short key id
        "dtk_" + uuid.uuid4().hex,  # missing secret entirely
        "dtk_" + uuid.uuid4().hex + "_",  # empty secret
        "Bearer dtk_" + uuid.uuid4().hex + "_secret",
    ],
)
def test_malformed_tokens_fail_to_parse(token):
    assert _parse_key(token) is None
