"""Consume encrypted tag requests authored by the repository's user owner.

The browser sends no API token. The owner confirms an encrypted issue in GitHub;
the scheduled job uses its short-lived GITHUB_TOKEN only against this repository.
"""
from __future__ import annotations

import json
import os
import re
import sys

import httpx

from cloud_tags import apply_cloud_changes, CloudTagError, TagConflict
from pages_crypto import decrypt, PackageError, password_bytes
from tag_import import validate_changes, TagImportError

TITLE = '[Anki Atlas] Encrypted tag update'
ATTENTION_TITLE = '[Anki Atlas] Tag update needs attention'
MARKER = '<!-- anki-atlas-tag-request:v1 -->'
MAX_BODY = 60000
MAX_REQUESTS = 5


class QueueError(ValueError):
    """No API response, secret, note text or decrypted tag enters an error."""


def parse_body(body, password):
    if not isinstance(body, str) or len(body.encode('utf-8')) > MAX_BODY:
        raise QueueError('Invalid encrypted request.')
    match = re.fullmatch(re.escape(MARKER) + r'\n```json\n([^\n]+)\n```\s*', body)
    if not match:
        raise QueueError('Invalid encrypted request.')
    try:
        return validate_changes(decrypt(json.loads(match[1]), password))
    except (PackageError, TagImportError, ValueError, RecursionError):
        raise QueueError('Invalid encrypted request.') from None


class GitHubQueue:
    def __init__(self, repository, token):
        if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise QueueError('Invalid repository.')
        if not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise QueueError('Set the job GitHub token.')
        self.base = 'https://api.github.com/repos/' + repository
        self.client = httpx.Client(headers={'Authorization': 'Bearer ' + token,
                                           'Accept': 'application/vnd.github+json',
                                           'X-GitHub-Api-Version': '2022-11-28'},
                                   timeout=30, follow_redirects=False)
        self.owner = None

    def __enter__(self):
        try:
            self.owner = self.request('GET', '')['owner']
            if self.owner.get('type') != 'User' or type(self.owner.get('id')) is not int or self.owner['id'] <= 0:
                raise QueueError('A personal repository with a user owner is required.')
        except Exception:
            self.client.close()
            raise
        return self

    def __exit__(self, *_):
        self.client.close()

    def request(self, method, path, **kwargs):
        try:
            with self.client.stream(method, self.base + path, **kwargs) as response:
                if response.status_code not in (200, 201):
                    raise QueueError('GitHub queue request failed; check job permissions and Issues settings.')
                size, chunks = 0, []
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 4 * 1024 * 1024:
                        raise QueueError('GitHub queue response is too large.')
                    chunks.append(chunk)
                return json.loads(b''.join(chunks))
        except (httpx.HTTPError, ValueError, KeyError, RecursionError):
            raise QueueError('GitHub queue request failed; private diagnostics were not logged.') from None

    def approved(self, issue):
        return (isinstance(issue, dict) and 'pull_request' not in issue
                and issue.get('state') == 'open' and issue.get('title') == TITLE
                and issue.get('user', {}).get('id') == self.owner['id']
                and type(issue.get('number')) is int and issue['number'] > 0)

    def pending(self):
        result = []
        for page in range(1, 21):
            issues = self.request('GET', '/issues', params={'state': 'open', 'creator': self.owner['login'],
                                  'sort': 'created', 'direction': 'asc', 'per_page': 30, 'page': page})
            if not isinstance(issues, list):
                raise QueueError('Invalid queue response.')
            for issue in issues:
                if self.approved(issue):
                    result.append(issue)
                    if len(result) >= MAX_REQUESTS:
                        return result
            if len(issues) < 30:
                break
        return result

    def current(self, issue):
        latest = self.request('GET', f"/issues/{issue['number']}")
        if not self.approved(latest) or latest.get('number') != issue.get('number') or latest.get('body') != issue.get('body'):
            return None
        return latest

    def acknowledge(self, issue):
        # An edit or cancellation during sync must not be acknowledged accidentally.
        if self.current(issue) is None:
            return
        number = issue['number']
        self.request('POST', f'/issues/{number}/comments', json={'body':
            'タグのAnkiWebへの反映を確認しました。スマホのAnkiで同期してください。Pagesの更新はこの実行の後続処理です。'})
        self.request('PATCH', f'/issues/{number}', json={'state': 'closed', 'state_reason': 'completed'})

    def reject(self, issue):
        if self.current(issue) is None:
            return
        number = issue['number']
        self.request('PATCH', f'/issues/{number}', json={'title': ATTENTION_TITLE})
        self.request('POST', f'/issues/{number}/comments', json={'body':
            '反映を確認できません。閲覧パスワード・送信データ・対象ノートを確認し、最新のPagesでタグを付け直して新しく送信してください。一部がすでに反映されている場合もあります。このリクエストは自動再試行しません。'})


def process_queue(queue, password, hkey, endpoint=None):
    password_bytes(password)
    result = {'applied': 0, 'rejected': 0, 'skipped': 0}
    for listed in queue.pending():
        issue = queue.current(listed)
        if issue is None:
            result['skipped'] += 1
            continue
        try:
            package = parse_body(issue.get('body'), password)
        except QueueError:
            queue.reject(issue)
            result['rejected'] += 1
            continue
        try:
            verified = apply_cloud_changes(package, hkey, endpoint)
            if not isinstance(verified, dict) or verified.get('verified') is not True:
                raise CloudTagError('Remote changes were not verified.')
        except TagConflict:
            queue.reject(issue)
            result['rejected'] += 1
            continue
        # Transient/uncertain failures propagate. Keep pending and retry idempotently.
        queue.acknowledge(issue)
        result['applied'] += 1
    return result


def main():
    if os.environ.get('ANKI_TAG_IMPORT_ENABLED') != 'true':
        print('Cloud tag import is disabled; no queue or AnkiWeb changes were accessed.')
        return 0
    try:
        password = os.environ.get('PAGES_PASSWORD', '')
        password_bytes(password)
        with GitHubQueue(os.environ.get('GITHUB_REPOSITORY', ''), os.environ.get('GITHUB_TOKEN', '')) as queue:
            result = process_queue(queue, password, os.environ.get('ANKIWEB_HKEY', ''),
                                   os.environ.get('ANKIWEB_ENDPOINT') or None)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('Cloud tag queue failed; pending requests will be retried. Check configuration, Anki sync and job permissions. Private diagnostics were not logged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
