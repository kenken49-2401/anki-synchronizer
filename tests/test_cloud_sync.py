"""Validate download-only refresh against Anki's official local sync server."""
import os
import socket
import subprocess
import sys
import time
from unittest.mock import patch

from anki.collection import Collection
from anki import sync_pb2
import pytest

import cloud_sync
from dashboard import validate_snapshot


def test_official_server_download_is_read_only(tmp_path, monkeypatch):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}/'
    monkeypatch.setenv('NO_PROXY', os.environ.get('NO_PROXY', '') + ',localhost,127.0.0.1')
    env = os.environ.copy()
    env.update(SYNC_HOST='127.0.0.1', SYNC_PORT=str(port), SYNC_BASE=str(tmp_path / 'remote'), SYNC_USER1='user:password')
    server = subprocess.Popen([sys.executable, '-m', 'anki.syncserver'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seed = None
    try:
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1): break
            except OSError: time.sleep(.03)
        seed = Collection(str(tmp_path / 'seed.anki2'))
        note = seed.new_note(seed.models.by_name('Basic'))
        note['Front'] = 'C<sub>2</sub>H<sub>4</sub>'
        note['Back'] = 'Polymer'
        seed.add_note(note, seed.decks.id('Chemistry'))
        auth = seed.sync_login('user', 'password', endpoint)
        seed.sync_collection(auth, sync_media=False)
        seed.close_for_full_sync()
        seed._backend.full_upload_or_download(sync_pb2.FullUploadOrDownloadRequest(auth=auth, upload=True))
        seed.reopen(after_full_sync=True)
        # Normal sync must never run in the cloud downloader.
        with patch.object(Collection, 'sync_collection', side_effect=AssertionError('normal sync forbidden')):
            result = cloud_sync.export_snapshot(auth.hkey, _test_endpoint=endpoint)
            second = cloud_sync.export_snapshot(auth.hkey, _test_endpoint=endpoint)
        assert result['cards'] == second['cards']
        assert result['source']['kind'] == 'ankiweb'
        assert len(result['cards']) == 1
        assert 'C<sub>2</sub>' in validate_snapshot(result)['cards'][0]['front_html']
        assert seed.db.scalar('select count(*) from cards') == 1
    finally:
        if seed: seed.close()
        server.terminate()
        server.wait(timeout=5)


@pytest.mark.parametrize('endpoint', ['http://sync.ankiweb.net/', 'https://evil.example/', 'https://ankiweb.net.evil.example/', 'https://sync.ankiweb.net/path', 'https://user@sync.ankiweb.net/', 'https://127.0.0.1/'])
def test_endpoint_rejects_token_exfiltration(endpoint):
    with pytest.raises(cloud_sync.CloudSyncError):
        cloud_sync.export_snapshot('secret-test-key', endpoint)


def test_failed_download_never_uploads(monkeypatch, capsys):
    monkeypatch.setenv('DASHBOARD_URL', 'https://study.example')
    monkeypatch.setenv('ANKI_UPLOAD_TOKEN', 'x' * 40)
    with patch.object(cloud_sync, 'export_snapshot', side_effect=cloud_sync.CloudSyncError('Download failed')), patch.object(cloud_sync, 'upload_snapshot') as upload:
        assert cloud_sync.main([]) == 1
        upload.assert_not_called()
    assert 'Download failed' in capsys.readouterr().err


def test_empty_collection_does_not_clear_dashboard(tmp_path):
    col = Collection(str(tmp_path / 'empty.anki2'))
    try:
        with pytest.raises(cloud_sync.CloudSyncError, match='No cards'):
            cloud_sync._extract_snapshot(col, timezone='Asia/Tokyo', query='', allow_empty=False)
        assert cloud_sync._extract_snapshot(col, timezone='Asia/Tokyo', query='', allow_empty=True)['cards'] == []
    finally:
        col.close()


def test_read_only_metadata_selects_collection_shard():
    from unittest.mock import Mock
    col = Mock()
    auth = sync_pb2.SyncAuth(hkey='test-secret-key', endpoint=cloud_sync.DEFAULT_ENDPOINT)
    col.sync_status.return_value = sync_pb2.SyncStatusResponse(new_endpoint='https://sync2.ankiweb.net/')
    cloud_sync.resolve_download_endpoint(col, auth)
    col.sync_status.assert_called_once_with(auth)
    assert auth.endpoint == 'https://sync2.ankiweb.net/'
    col.sync_collection.assert_not_called()
    col.sync_media.assert_not_called()


@pytest.mark.parametrize('endpoint', ['https://evil.example/', 'https://user@sync2.ankiweb.net/', 'http://sync2.ankiweb.net/'])
def test_discovered_shard_is_validated(endpoint):
    from unittest.mock import Mock
    col = Mock()
    auth = sync_pb2.SyncAuth(hkey='test-secret-key', endpoint=cloud_sync.DEFAULT_ENDPOINT)
    col.sync_status.return_value = sync_pb2.SyncStatusResponse(new_endpoint=endpoint)
    with pytest.raises(cloud_sync.CloudSyncError):
        cloud_sync.resolve_download_endpoint(col, auth)
    assert auth.endpoint == cloud_sync.DEFAULT_ENDPOINT


def test_export_omits_repeated_template_css_and_keeps_html_identity(tmp_path, monkeypatch):
    from note_identity import note_fingerprint
    import connector
    col = Collection(str(tmp_path / 'styled.anki2'))
    try:
        model = col.models.by_name('Basic')
        model['css'] = '/* repeated template style */' * 1000
        col.models.save(model)
        for i in range(8):
            note = col.new_note(model)
            note['Front'] = f'H<sub>2</sub>O {i}<img src="molecule.png">'
            note['Back'] = '<b>Water</b>'
            col.add_note(note, col.decks.id('Chemistry'))
        monkeypatch.setattr(connector, 'MAX_SNAPSHOT_BYTES', 10000)
        data = cloud_sync._extract_snapshot(col, timezone='Asia/Tokyo', query='', allow_empty=False)
        assert len(data['cards']) == 8
        for card in data['cards']:
            assert model['css'] not in card['front'] + card['back']
            assert '<sub>2</sub>' in card['front']
            assert 'molecule.png' in card['front']
            assert '<b>Water</b>' in card['back']
            safe = validate_snapshot({**data, 'cards': [card], 'reviews': []})['cards'][0]
            assert safe['tag_identity'] == note_fingerprint(card['model'], card['fields'])
    finally:
        col.close()
