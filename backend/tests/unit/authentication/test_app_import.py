import pytest

from app.main import app

pytestmark = pytest.mark.unit


def test_app_imports() -> None:
    assert app.title == "MBGA Backend"
