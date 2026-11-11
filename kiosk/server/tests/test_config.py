import pytest
from pydantic import ValidationError

from kiosk_server.config import Settings


@pytest.mark.parametrize(
    "issuer",
    [
        "https://iden.example.org",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://192.168.1.20:8000",
        "http://10.0.0.5",
    ],
)
def test_prod_accepts_https_or_a_network_it_controls(issuer):
    assert Settings(kiosk_env="prod", kiosk_issuer=issuer).kiosk_issuer == issuer


@pytest.mark.parametrize("issuer", ["http://iden.example.org", "http://8.8.8.8"])
def test_prod_refuses_plain_http_across_the_internet(issuer):
    with pytest.raises(ValidationError, match="https"):
        Settings(kiosk_env="prod", kiosk_issuer=issuer)


def test_development_accepts_anything():
    assert Settings(kiosk_env="dev", kiosk_issuer="http://iden.example.org")
