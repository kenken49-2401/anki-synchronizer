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


def test_exports_scheduling_previous_intervals_fsrs_and_native_graphs(tmp_path):
    import time
    from anki.cards import FSRSMemoryState
    col = Collection(str(tmp_path / 'statistics.anki2'))
    try:
        note = col.new_note(col.models.by_name('Basic'))
        note['Front'] = 'Synthetic statistics fixture'
        col.add_note(note, col.decks.id('Statistics'))
        card = col.get_card(note.card_ids()[0])
        card.type = 2
        card.queue = 2
        card.ivl = 40
        card.factor = 2350
        card.due = col.sched.today + 1
        card.memory_state = FSRSMemoryState(stability=40, difficulty=5)
        card.desired_retention = .9
        col.update_card(card)
        rid = int(time.time() * 1000) - 1000
        col.db.execute('insert into revlog values (?,?,?,?,?,?,?,?,?)', rid, card.id, -1, 1, 1, 30, 2350, 2000, 1)
        raw = cloud_sync._extract_snapshot(col, timezone='Asia/Tokyo', query='', allow_empty=False)
        safe = validate_snapshot(raw)
        assert safe['cards'][0]['type'] == 2
        assert safe['cards'][0]['queue'] == 2
        assert safe['cards'][0]['ease_factor'] == 2350
        assert safe['cards'][0]['stability'] == 40
        assert safe['cards'][0]['difficulty'] == 5
        assert safe['cards'][0]['desired_retention'] == pytest.approx(.9)
        native_card_stats = col._backend.card_stats(cid=int(card.id))
        if native_card_stats.HasField('fsrs_retrievability'):
            assert safe['cards'][0]['retrievability'] == pytest.approx(native_card_stats.fsrs_retrievability)
            assert 0 <= safe['cards'][0]['retrievability'] <= 1
        else:
            assert 'retrievability' not in safe['cards'][0]
        assert safe['cards'][0]['added_at'] == card.id
        assert safe['cards'][0]['due_date']
        assert safe['reviews'][0]['last_interval'] == 30
        assert safe['reviews'][0]['interval'] == 1
        assert safe['source']['rollover_hour'] == 4
        assert safe['source']['history_scope'] == 'collection'
        assert safe['source']['orphan_review_count'] == 0
        assert safe['source']['collection_review_count'] == 1
        native = safe['native_statistics']['graphs']
        assert native['true_retention']['all_time']['mature_failed'] == 1
        assert native['card_counts']['excluding_inactive']['mature'] == 1
    finally:
        col.close()


def test_pure_analytics_agree_with_pinned_anki_native_graphs(tmp_path):
    """Compare actual native statistics against the browser's pure analytics."""
    import json
    import shutil
    from pathlib import Path
    if not shutil.which('node'):
        pytest.skip('Node is needed for the cross-language statistics comparison')
    col = Collection(str(tmp_path / 'native-comparison.anki2'))
    try:
        note = col.new_note(col.models.by_name('Basic'))
        note['Front'] = 'Native comparison fixture'
        col.add_note(note, col.decks.id('Comparison'))
        card = col.get_card(note.card_ids()[0])
        card.type, card.queue, card.ivl, card.factor = 2, 2, 30, 2350
        card.due = col.sched.today + 1
        col.update_card(card)
        timestamp = int(time.time() * 1000) - 10000
        for i, (kind, ease, prior) in enumerate([(0, 3, 0), (1, 1, 21), (1, 3, 1), (2, 3, -30), (3, 3, 1), (4, 0, 1), (5, 0, 1)]):
            col.db.execute('insert into revlog values (?,?,?,?,?,?,?,?,?)', timestamp+i, card.id, -1, ease, 1, prior, 2350, 1000, kind)
        # Deleted-card records are real collection history; raw per-card analytics
        # cannot attribute them. Native collection graphs retain Anki's authority.
        col.db.execute('insert into revlog values (?,?,?,?,?,?,?,?,?)', timestamp+99, card.id+100, -1, 3, 10, 21, 2350, 3000, 1)
        zone = os.environ.get('TZ', 'UTC')
        snapshot = cloud_sync._extract_snapshot(col, timezone=zone, query='', allow_empty=False)
        assert snapshot['source']['orphan_review_count'] == 1
        assert snapshot['source']['collection_review_count'] == 8
        assert len(snapshot['reviews']) == 7
        assert len(snapshot['orphan_reviews']) == 1
        assert validate_snapshot(snapshot)['orphan_reviews'] == snapshot['orphan_reviews']
        snapshot_path = tmp_path / 'snapshot.json'
        snapshot_path.write_text(json.dumps(snapshot))
        script = "import fs from 'node:fs'; import {ankiStatistics} from './web/stats.mjs'; console.log(JSON.stringify(ankiStatistics(JSON.parse(fs.readFileSync(process.argv[1],'utf8')),{days:30})));"
        process = subprocess.run(['node', '--input-type=module', '-e', script, str(snapshot_path)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
        stats = json.loads(process.stdout)
        native = snapshot['native_statistics']['graphs']
        assert stats['today']['count'] == native['today']['answer_count'] == 6
        assert stats['today']['time'] == native['today']['answer_millis'] == 8000
        assert stats['today']['correct'] == native['today']['correct_count'] == 5
        assert stats['cardCounts']['mature'] == native['card_counts']['excluding_inactive']['mature'] == 1
        assert stats['futureDue']['tomorrow'] == native['future_due']['future_due']['1'] == 1
        assert stats['answerButtons']['learn'] == native['buttons']['all_time']['learning']
        assert stats['answerButtons']['young'] == native['buttons']['all_time']['young']
        assert stats['answerButtons']['mature'] == native['buttons']['all_time']['mature']
        retention = next(row for row in stats['retention'] if row['period'] == 'all')
        actual = native['true_retention']['all_time']
        assert retention['young']['correct'] == actual['young_passed'] == 2
        assert retention['mature']['count'] - retention['mature']['correct'] == actual['mature_failed'] == 1
        assert sum(row['count'] for row in stats['hourly']) == sum(row.get('total', 0) for row in native['hours']['all_time']) == 5
    finally:
        col.close()


@pytest.mark.parametrize('kind,queue,interval,factor,seconds_due', [
    (0, 0, 0, 2355, False), (0, -2, 0, 2355, False),
    (1, 1, 0, 2355, True), (1, 3, 0, 2355, False),
    (1, -2, 0, 2355, False), (1, -3, 0, 2355, False),
    (1, -2, 0, 2355, True), (1, -1, 0, 2355, False),
    (2, 2, 40, 2355, False), (2, -1, 40, 2355, False),
    (2, -2, 40, 2355, False), (2, -3, 40, 2355, False),
    (3, 1, 40, 2355, True), (3, 3, 40, 2355, False),
    (3, -1, 40, 2355, False), (3, -2, 40, 2355, False),
    (3, -3, 40, 2355, False), (3, -2, 40, 2355, True),
    (2, 2, 0, 0, False), (3, 3, 0, 0, False),
])
def test_scheduling_distributions_and_due_match_native_state_matrix(tmp_path, kind, queue, interval, factor, seconds_due):
    import json
    import shutil
    from pathlib import Path
    if not shutil.which('node'):
        pytest.skip('Node is needed for the cross-language statistics comparison')
    col = Collection(str(tmp_path / 'state-matrix.anki2'))
    try:
        note = col.new_note(col.models.by_name('Basic'))
        note['Front'] = 'Synthetic scheduling parity fixture'
        col.add_note(note, col.decks.id('Parity'))
        card = col.get_card(note.card_ids()[0])
        card.type, card.queue, card.ivl, card.factor = kind, queue, interval, factor
        card.due = int(time.time()) + 86400 if seconds_due else col.sched.today + 1
        col.update_card(card)
        snapshot = cloud_sync._extract_snapshot(col, timezone=os.environ.get('TZ', 'UTC'), query='', allow_empty=False)
        native = snapshot['native_statistics']['graphs']
        script = "import {ankiStatistics} from './web/stats.mjs'; let s=''; for await(const c of process.stdin)s+=c; console.log(JSON.stringify(ankiStatistics(JSON.parse(s))));"
        process = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(snapshot), cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
        stats = json.loads(process.stdout)
        assert {str(row['day']): row['count'] for row in stats['futureDue']['bins']} == native.get('future_due', {}).get('future_due', {})
        assert stats['futureDue']['workload'] == native.get('future_due', {}).get('daily_load', 0)
        assert {str(row['value']): row['count'] for row in stats['intervals']['bins']} == native.get('intervals', {}).get('intervals', {})
        assert {str(row['value']): row['count'] for row in stats['ease']['bins']} == native.get('eases', {}).get('eases', {})
        if stats['ease']['count']:
            assert stats['ease']['average'] == native.get('eases', {}).get('average', 0)
        for state, count in native['card_counts']['excluding_inactive'].items():
            assert stats['cardCounts']['new' if state == 'newCards' else state] == count
        if kind in (1, 3) and queue in (-2, -3):
            assert ('due_date' in snapshot['cards'][0]) is not seconds_due
    finally:
        col.close()


def test_cli_restores_runtime_timezone_after_configuration_failure(monkeypatch):
    if not hasattr(time, 'tzset'):
        pytest.skip('POSIX local timezone setting')
    original = os.environ.get('TZ')
    monkeypatch.setenv('TZ', 'UTC')
    time.tzset()
    monkeypatch.delenv('DASHBOARD_URL', raising=False)
    try:
        assert cloud_sync.main(['--timezone', 'Asia/Tokyo']) == 1
        assert os.environ['TZ'] == 'UTC'
        assert time.localtime(0).tm_hour == 0
    finally:
        if original is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = original
        time.tzset()
