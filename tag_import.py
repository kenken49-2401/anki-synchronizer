"""Apply encrypted browser tag additions to the already-open local Anki profile.

Dry-run is the default. This module never switches profiles or removes tags.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import getpass
import json
import os
import re
from pathlib import Path
import stat
import sys
import unicodedata
from typing import Any

from note_identity import note_fingerprint
from connector import AnkiConnect, BATCH_SIZE, ConnectorError, MAX_ID
from pages_crypto import MAX_PACKAGE_BYTES, PackageError, decrypt


class TagImportError(ValueError):
    """Safe to display: messages never contain imported or remote content."""


def _invalid() -> None:
    raise TagImportError("Invalid tag-change package.")


def _text(value: Any, maximum: int, *, nonempty: bool = False) -> bool:
    return (isinstance(value, str) and len(value) <= maximum
            and (not nonempty or bool(value.strip()))
            and all(c != '\x00' and unicodedata.category(c) != 'Cs' for c in value))


def _id(value: Any) -> bool:
    return type(value) is int and 1 <= value <= MAX_ID


def validate_changes(value: Any) -> dict[str, Any]:
    """Validate the complete addition-only contract before contacting Anki."""
    if (not isinstance(value, dict)
            or set(value) != {'format', 'version', 'created_at', 'source', 'changes'}
            or value['format'] != 'anki-atlas-tag-changes'
            or type(value['version']) is not int or value['version'] != 1
            or not _text(value['created_at'], 64)):
        _invalid()
    try:
        if datetime.fromisoformat(value['created_at'].replace('Z', '+00:00')).tzinfo is None:
            _invalid()
    except ValueError:
        _invalid()
    source = value['source']
    if (not isinstance(source, dict) or set(source) != {'kind', 'profile'}
            or source['kind'] not in ('ankiconnect', 'ankiweb')
            or not _text(source['profile'], 256, nonempty=True)):
        _invalid()
    changes = value['changes']
    if not isinstance(changes, list) or len(changes) > 50_000:
        _invalid()
    notes, cards = set(), set()
    for change in changes:
        if (not isinstance(change, dict)
                or set(change) != {'note_id', 'card_ids', 'model', 'fingerprint', 'add_tags'}
                or not _id(change['note_id']) or change['note_id'] in notes
                or not _text(change['model'], 256, nonempty=True)):
            _invalid()
        notes.add(change['note_id'])
        ids, tags = change['card_ids'], change['add_tags']
        if not isinstance(ids, list) or not 1 <= len(ids) <= 50_000:
            _invalid()
        for card_id in ids:
            if not _id(card_id) or card_id in cards or len(cards) >= 50_000:
                _invalid()
            cards.add(card_id)
        if (not isinstance(change['fingerprint'], str)
                or re.fullmatch(r'[0-9a-f]{64}', change['fingerprint']) is None):
            _invalid()
        if not isinstance(tags, list) or not 1 <= len(tags) <= 100:
            _invalid()
        seen_tags = set()
        for tag in tags:
            if (not _text(tag, 128, nonempty=True)
                    or any(c.isspace() or unicodedata.category(c).startswith('C') or c in '*?' for c in tag)
                    or tag in seen_tags):
                _invalid()
            seen_tags.add(tag)
    return value


def read_changes(path: str | Path, password: str) -> dict[str, Any]:
    """Bounded read of a regular, non-symlink encrypted file."""
    descriptor = None
    try:
        # O_NOFOLLOW also closes the check/open race for the final path component.
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode):
            _invalid()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PACKAGE_BYTES
                or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)):
            _invalid()
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            encoded = stream.read(MAX_PACKAGE_BYTES + 1)
        if len(encoded) > MAX_PACKAGE_BYTES:
            _invalid()
        return validate_changes(decrypt(json.loads(encoded), password))
    except TagImportError:
        raise
    except (OSError, ValueError, UnicodeError, PackageError, RecursionError):
        raise TagImportError("Cannot read or decrypt the tag-change package; check the file and password.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _records(anki: AnkiConnect, action: str, parameter: str, key: str,
             ids: list[int]) -> dict[int, dict[str, Any]]:
    result = {}
    for offset in range(0, len(ids), BATCH_SIZE):
        batch = ids[offset:offset + BATCH_SIZE]
        rows = anki.call(action, **{parameter: batch})
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise TagImportError("Anki identity verification failed; refresh the snapshot and retry.")
        for row in rows:
            if (not isinstance(row, dict) or not _id(row.get(key))
                    or row[key] not in batch or row[key] in result):
                raise TagImportError("Anki identity verification failed; refresh the snapshot and retry.")
            result[row[key]] = row
    return result


def _identity(note: dict[str, Any], change: dict[str, Any]) -> set[str]:
    fields = note.get('fields')
    if (note.get('modelName') != change['model'] or not isinstance(fields, dict)
            or not fields or len(fields) > 64
            or any(not _text(k, 256, nonempty=True) or not isinstance(v, dict)
                   or not _text(v.get('value'), 128_000) for k, v in fields.items())
            or not isinstance(note.get('tags'), list)
            or any(not isinstance(tag, str) for tag in note['tags'])):
        raise TagImportError("Anki identity verification failed; refresh the snapshot and retry.")
    if note_fingerprint(note['modelName'], {k: v['value'] for k, v in fields.items()}) != change['fingerprint']:
        raise TagImportError("Anki identity verification failed; refresh the snapshot and retry.")
    return set(note['tags'])


def import_tag_changes(path: str | Path, password: str, expected_profile: str, *,
                       endpoint: str = 'http://127.0.0.1:8765', api_key: str | None = None,
                       apply: bool = False, sync: bool = False) -> dict[str, int | bool]:
    """Preflight all identities, optionally add missing tags, verify, then sync.

    Late failures may leave additions in Anki. Retrying the same file is safe.
    No sync is attempted after an import or verification failure.
    """
    if sync and not apply:
        raise TagImportError("--sync requires --apply.")
    package = read_changes(path, password)
    if (not _text(expected_profile, 256, nonempty=True)
            or (package['source']['kind'] == 'ankiconnect'
                and package['source']['profile'] != expected_profile)):
        raise TagImportError("Package profile does not match the required profile.")
    changes = package['changes']
    attempted = False
    sync_attempted = False
    try:
        with AnkiConnect(endpoint, api_key) as anki:
            def check_profile() -> None:
                if anki.active_profile() != expected_profile:
                    raise TagImportError("The open Anki profile does not match the required profile.")

            check_profile()
            notes = _records(anki, 'notesInfo', 'notes', 'noteId', [c['note_id'] for c in changes])
            cards = _records(anki, 'cardsInfo', 'cards', 'cardId', [i for c in changes for i in c['card_ids']])
            original, pending = {}, {}
            for change in changes:
                nid = change['note_id']
                original[nid] = _identity(notes[nid], change)
                if any(type(cards[cid].get('note')) is not int or cards[cid]['note'] != nid
                       for cid in change['card_ids']):
                    raise TagImportError("Anki card identity verification failed; refresh the snapshot and retry.")
                existing = {tag.lower() for tag in original[nid]}
                pending[nid] = []
                for tag in change['add_tags']:
                    if tag.lower() not in existing:
                        pending[nid].append(tag)
                        existing.add(tag.lower())
            result = {'notes': len(changes), 'notes_to_update': sum(bool(t) for t in pending.values()),
                      'tags_to_add': sum(map(len, pending.values())), 'applied': apply, 'synced': False}
            if not apply:
                return result
            check_profile()
            for nid, tags in pending.items():
                if tags:
                    # Profile selection is never changed by this importer.
                    check_profile()
                    attempted = True
                    anki.call('addTags', notes=[nid], tags=' '.join(tags))
            check_profile()
            after = _records(anki, 'notesInfo', 'notes', 'noteId', list(pending))
            for change in changes:
                tags = _identity(after[change['note_id']], change)
                expected = {t.lower() for t in original[change['note_id']].union(change['add_tags'])}
                if not expected <= {t.lower() for t in tags}:
                    raise TagImportError("Tag verification failed.")
            if sync:
                check_profile()
                sync_attempted = True
                anki.call('sync')
                result['synced'] = True
            return result
    except (ConnectorError, TagImportError):
        if sync_attempted:
            raise TagImportError("Tag additions were verified, but sync completion is not confirmed. Check Anki before retrying sync.") from None
        if attempted:
            raise TagImportError("Import did not complete. Some additions may already be saved; retrying is safe. Sync completion is not confirmed.") from None
        raise TagImportError("Import stopped before writing. Check the local Anki connection, profile, and snapshot identity.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--profile', required=True, help='Expected already-open Anki profile')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8765')
    parser.add_argument('--apply', action='store_true', help='Write additions (default: dry-run)')
    parser.add_argument('--sync', action='store_true', help='Sync Anki after successful --apply and verification')
    args = parser.parse_args(argv)
    if args.sync and not args.apply:
        parser.error('--sync requires --apply')
    try:
        password = os.environ.get('PAGES_PASSWORD')
        if password is None:
            password = getpass.getpass('Pages password: ')
        result = import_tag_changes(args.file, password, args.profile, endpoint=args.endpoint,
                                    api_key=os.environ.get('ANKI_CONNECT_API_KEY'), apply=args.apply, sync=args.sync)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (TagImportError, EOFError, KeyboardInterrupt):
        print('Tag import failed. Check the package, password, profile, and local Anki state. '
              'If applying, some additions may already be saved; retrying is safe. Sync completion is not confirmed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
