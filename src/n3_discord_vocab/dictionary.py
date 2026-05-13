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
    meaning_language: str = "en"


ZH_DICTIONARY = {
    "敢えて": ("敢えて", "あえて", "故意、刻意、特意、硬要、不一定、不特別", "adverb"),
    "あえて": ("敢えて", "あえて", "故意、刻意、特意、硬要、不一定、不特別", "adverb"),
    "やがて": ("やがて", "やがて", "不久、終於、最後", "adverb"),
    "いきなり": ("いきなり", "いきなり", "突然、冷不防", "adverb"),
    "ぼんやり": ("ぼんやり", "ぼんやり", "模糊地、發呆地、心不在焉", "adverb"),
    "締め切り": ("締め切り", "しめきり", "截止、期限", "noun"),
    "締切": ("締め切り", "しめきり", "截止、期限", "noun"),
    "承る": ("承る", "うけたまわる", "聽取、承蒙、接受、受理", "verb"),
    "慌てる": ("慌てる", "あわてる", "慌張、急忙、手忙腳亂", "verb"),
    "預ける": ("預ける", "あずける", "寄放、託付、交給保管", "verb"),
    "抱える": ("抱える", "かかえる", "抱著、背負、承擔問題", "verb"),
    "勘違い": ("勘違い", "かんちがい", "誤會、會錯意", "noun"),
    "改めて": ("改めて", "あらためて", "再次、重新、正式地", "adverb"),
    "余計": ("余計", "よけい", "多餘、更加、額外", "na-adjective"),
    "案外": ("案外", "あんがい", "意外地、出乎意料", "adverb"),
    "一応": ("一応", "いちおう", "姑且、暫且、大致上", "adverb"),
    "妙": ("妙", "みょう", "奇怪、微妙、巧妙", "na-adjective"),
    "徹夜": ("徹夜", "てつや", "熬夜、通宵", "noun"),
    "省く": ("省く", "はぶく", "省略、刪去、節省", "verb"),
    "任せる": ("任せる", "まかせる", "交給、委託、任憑", "verb"),
    "悔しい": ("悔しい", "くやしい", "懊悔、不甘心", "i-adjective"),
    "ずらす": ("ずらす", "ずらす", "挪開、錯開、延後", "verb"),
    "わざと": ("わざと", "わざと", "故意地、有意地", "adverb"),
}


class DictionaryClient:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def lookup(self, keyword: str) -> DictionaryEntry | None:
        if not self.enabled:
            return None
        keyword = keyword.strip()
        if not keyword:
            return None
        return self._lookup_zh(keyword) or self._lookup_jisho(keyword)

    def _lookup_zh(self, keyword: str) -> DictionaryEntry | None:
        row = ZH_DICTIONARY.get(keyword)
        if not row:
            return None
        surface, reading, meaning, part_of_speech = row
        return DictionaryEntry(
            surface=surface,
            reading=reading,
            meaning=meaning,
            part_of_speech=part_of_speech,
            source="local_zh",
            meaning_language="zh",
        )

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
