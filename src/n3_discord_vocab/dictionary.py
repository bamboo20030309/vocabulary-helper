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
    examples: tuple[tuple[str, str], ...] = ()


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

ZH_EXAMPLES = {
    "敢えて": ("彼は敢えて何も言わなかった。", "他故意什麼都沒說。"),
    "やがて": ("雨はやがて止むでしょう。", "雨不久會停吧。"),
    "いきなり": ("彼はいきなり大きな声を出した。", "他突然大聲叫了出來。"),
    "ぼんやり": ("疲れて、窓の外をぼんやり見ていた。", "累了，所以發呆地看著窗外。"),
    "締め切り": ("締め切りまであと二日しかない。", "離截止日期只剩兩天了。"),
    "承る": ("ご注文は私が承ります。", "您的訂單由我來受理。"),
    "慌てる": ("電車の時間を見て慌てた。", "看到電車時間後慌了起來。"),
}

NEW_WORD_CANDIDATES = {
    "せめて": ("せめて", "せめて", "至少、起碼", "adverb"),
    "むしろ": ("むしろ", "むしろ", "倒不如、反而", "adverb"),
    "なかなか": ("なかなか", "なかなか", "相當、頗、怎麼也不", "adverb"),
    "すっかり": ("すっかり", "すっかり", "完全、徹底", "adverb"),
    "なるべく": ("なるべく", "なるべく", "盡量、儘可能", "adverb"),
    "たびたび": ("たびたび", "たびたび", "屢次、常常", "adverb"),
    "ついでに": ("ついでに", "ついでに", "順便", "adverb"),
    "余る": ("余る", "あまる", "剩下、多出", "verb"),
    "支える": ("支える", "ささえる", "支撐、支持", "verb"),
    "断る": ("断る", "ことわる", "拒絕、事先告知", "verb"),
    "眺める": ("眺める", "ながめる", "眺望、凝視", "verb"),
    "通じる": ("通じる", "つうじる", "相通、理解、通往", "verb"),
    "試す": ("試す", "ためす", "嘗試、試驗", "verb"),
    "失う": ("失う", "うしなう", "失去、喪失", "verb"),
    "避ける": ("避ける", "さける", "避開、避免", "verb"),
    "比べる": ("比べる", "くらべる", "比較", "verb"),
    "似合う": ("似合う", "にあう", "適合、相稱", "verb"),
    "積極的": ("積極的", "せっきょくてき", "積極的", "na-adjective"),
    "消極的": ("消極的", "しょうきょくてき", "消極的", "na-adjective"),
    "貴重": ("貴重", "きちょう", "貴重、珍貴", "na-adjective"),
    "平等": ("平等", "びょうどう", "平等", "na-adjective"),
    "迷惑": ("迷惑", "めいわく", "麻煩、困擾", "na-adjective"),
    "苦労": ("苦労", "くろう", "辛苦、勞苦", "noun"),
    "環境": ("環境", "かんきょう", "環境", "noun"),
    "状態": ("状態", "じょうたい", "狀態", "noun"),
    "原因": ("原因", "げんいん", "原因", "noun"),
    "結果": ("結果", "けっか", "結果", "noun"),
}

ZH_DICTIONARY.update(NEW_WORD_CANDIDATES)


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

    def new_word_candidates(self) -> list[DictionaryEntry]:
        entries = []
        for key in NEW_WORD_CANDIDATES:
            entry = self._lookup_zh(key)
            if entry:
                entries.append(entry)
        return entries

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
            examples=(ZH_EXAMPLES[row[0]],) if row[0] in ZH_EXAMPLES else (),
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
