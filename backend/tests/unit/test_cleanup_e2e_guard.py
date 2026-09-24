import importlib.util
import secrets
from pathlib import Path

import pytest

from app.config.app import Settings

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_e2e_test_data.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("cleanup_e2e_test_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LOCAL_DB = "mysql+asyncmy://user:pw@127.0.0.1:3306/mbga?charset=utf8mb4"


@pytest.mark.parametrize("env", ["local", "development", "test"])
def test_cleanup_allowed_for_local_database(env: str) -> None:
    script = _load_script()
    script.ensure_safe_target(Settings(_env_file=None, app_env=env, database_url=LOCAL_DB))


@pytest.mark.parametrize("env", ["production", "staging", "prod"])
def test_cleanup_refuses_non_local_environments(env: str) -> None:
    script = _load_script()
    with pytest.raises(SystemExit):
        script.ensure_safe_target(Settings(_env_file=None, app_env=env, database_url=LOCAL_DB, jwt_signing_secret=secrets.token_urlsafe(48), sms_provider="sms"))


def test_cleanup_refuses_remote_database_even_in_development() -> None:
    script = _load_script()
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="mysql+asyncmy://user:pw@db.example.com:3306/mbga",
    )
    with pytest.raises(SystemExit):
        script.ensure_safe_target(settings)


def test_selection_rule_constants_are_strict() -> None:
    script = _load_script()
    assert script.E2E_CODE_PREFIX == "E2E-"
    assert script.E2E_NAME_PREFIX == "E2E "
    assert script.E2E_EMAIL_SUFFIX == "@example.invalid"


def test_mobile_numbers_are_masked_in_reports() -> None:
    script = _load_script()
    assert script.mask_mobile("+919999900011") == "+91******0011"
    assert script.mask_mobile(None) == "-"
