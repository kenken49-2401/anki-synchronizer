from unittest.mock import patch

import httpx
import pytest

from scripts import pages_bootstrap
from pages_site import ASSETS, BUILD_FILE


@pytest.mark.parametrize("status", [200, 301, 403, 500])
def test_bootstrap_preserves_existing_or_unknown_deployment(tmp_path, status):
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    output = tmp_path / "site"
    with patch.object(pages_bootstrap.httpx, "Client", return_value=client):
        with pytest.raises(ValueError):
            pages_bootstrap.bootstrap("https://example.test/atlas/", output)
    assert not output.exists()


def test_bootstrap_publishes_only_interface_without_password(tmp_path, monkeypatch):
    monkeypatch.delenv("PAGES_PASSWORD", raising=False)
    monkeypatch.delenv("ANKIWEB_HKEY", raising=False)
    requested = []

    def missing(request):
        requested.append(str(request.url))
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(missing))
    output = tmp_path / "site"
    with patch.object(pages_bootstrap.httpx, "Client", return_value=client):
        pages_bootstrap.bootstrap("https://example.test/atlas/", output)
    assert requested == ["https://example.test/atlas/snapshot.enc.json"]
    assert {p.name for p in output.iterdir()} == ASSETS | {BUILD_FILE, ".nojekyll"}
    assert 'name="anki-atlas-setup" content="pending"' in (output / "index.html").read_text()
    assert "__ATLAS_BUILD__" not in (output / "index.html").read_text()


def test_bootstrap_keeps_local_existing_output(tmp_path):
    private = tmp_path / "snapshot.enc.json"
    private.write_text("keep existing ciphertext")
    with patch.object(pages_bootstrap.httpx, "Client") as client:
        with pytest.raises(ValueError):
            pages_bootstrap.bootstrap("https://example.test/atlas/", tmp_path)
    client.assert_not_called()
    assert private.read_text() == "keep existing ciphertext"


def test_bootstrap_network_failure_stops_publication(tmp_path):
    def unavailable(request):
        raise httpx.ConnectError("unavailable", request=request)

    client = httpx.Client(transport=httpx.MockTransport(unavailable))
    output = tmp_path / "site"
    with patch.object(pages_bootstrap.httpx, "Client", return_value=client):
        with pytest.raises(httpx.ConnectError):
            pages_bootstrap.bootstrap("https://example.test/atlas/", output)
    assert not output.exists()
