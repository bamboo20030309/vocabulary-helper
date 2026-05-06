from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class DictionaryEntry:
    surface: str
    reading: str
    meaning: str
    part_of_speech: str = ""
    source: str = "jisho"


class DictionaryClient:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def lookup(self, keyword: str) -> DictionaryEntry | None:
        if not self.enabled:
            return None
        keyword = keyword.strip()
        if not keyword:
            return None
        return self._lookup_jisho(keyword)

    def _lookup_jisho(self, keyword: str) -> DictionaryEntry | None:
        query = urllib.parse.quote(keyword)
        url = f"https://jisho.org/api/v1/search/words?keyword={query}"
        req = urllib.request.Request(url, headers={"User-Agent": "n3-discord-vocab/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, json.JSONDecodeError):
            return None

        for item in payload.get("data", []):
            japanese = item.get("japanese") or []
            senses = item.get("senses") or []
            if not japanese or not senses:
                continue
            jp = japanese[0]
            surface = jp.get("word") or jp.get("reading") or keyword
            reading = jp.get("reading") or surface
            english = []
            parts = []
            for sense in senses[:2]:
                english.extend(sense.get("english_definitions") or [])
                parts.extend(sense.get("parts_of_speech") or [])
            if not english:
                continue
            return DictionaryEntry(
                surface=surface,
                reading=reading,
                meaning=", ".join(english[:6]),
                part_of_speech=", ".join(dict.fromkeys(parts[:3])),
            )
        return None
