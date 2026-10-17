"""Bounded raster attachments and a minimal card-formatting allowlist."""
from __future__ import annotations
import base64
import hashlib
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote

MAX_MEDIA_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MEDIA_FILES = 10_000


def filename(value):
    if not isinstance(value, str):
        return None
    value = unquote(value)
    if not value or len(value) > 255 or any(c in value for c in '/\\:\x00') or value in {'.', '..'}:
        return None
    return value


def raster(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    return None


def validate_media(raw):
    if not isinstance(raw, dict) or len(raw) > MAX_MEDIA_FILES:
        raise ValueError('media image count exceeds the supported limit')
    result = {}
    total = 0
    for name, item in raw.items():
        if filename(name) != name or not isinstance(item, dict) or not isinstance(item.get('data'), str):
            raise ValueError('Invalid media attachment')
        if len(item['data']) > (MAX_MEDIA_BYTES + 2) // 3 * 4:
            raise ValueError('Image exceeds 2 MiB')
        try: data = base64.b64decode(item['data'], validate=True)
        except ValueError: raise ValueError('Invalid image encoding') from None
        mime = raster(data)
        total += len(data)
        if not mime or mime != item.get('mime') or len(data) > MAX_MEDIA_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('Unsupported or oversized raster image')
        result[name] = {'mime': mime, 'data': item['data'], 'id': hashlib.sha256(data).hexdigest()}
    return result


class RichCard(HTMLParser):
    allowed = {'p', 'div', 'span', 'br', 'hr', 'strong', 'b', 'em', 'i', 'u', 's', 'sub', 'sup', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'pre', 'code'}
    hidden_tags = {'script', 'style', 'iframe', 'object', 'template', 'noscript', 'svg', 'math'}
    def __init__(self, media=None, answer_only=False):
        super().__init__(convert_charrefs=True)
        self.media = media or {}
        self.parts = []
        self.hidden = []
        self.answer_only = answer_only
        self.references = set()
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.answer_only and not self.hidden and tag == 'hr' and attrs.get('id') == 'answer':
            self.parts.clear()
            self.references.clear()
            self.answer_only = False
            return
        if tag in self.hidden_tags:
            self.hidden.append(tag)
        elif not self.hidden:
            if tag == 'img':
                name = filename(attrs.get('src'))
                if name:
                    self.references.add(name)
                item = self.media.get(name)
                if item:
                    self.parts.append(f'<img src="./api/media/{item["id"]}" alt="{escape(attrs.get("alt") or "カードの図", quote=True)}" loading="lazy">')
                else:
                    self.parts.append('<span class="missing-media">［画像未取得］</span>')
            elif tag in self.allowed:
                self.parts.append(f'<{tag}>')
    def handle_endtag(self, tag):
        if self.hidden:
            if self.hidden[-1] == tag: self.hidden.pop()
        elif tag in self.allowed and tag not in {'br', 'hr'}:
            self.parts.append(f'</{tag}>')
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.hidden_tags: self.handle_endtag(tag)
    def handle_data(self, data):
        if not self.hidden: self.parts.append(escape(data))


def rich(value, media=None, answer_only=False):
    parser = RichCard(media, answer_only)
    parser.feed(value)
    parser.close()
    return ''.join(parser.parts), parser.references
