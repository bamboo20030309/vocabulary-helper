from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import Label


LABEL_HINTS = {
    "會": Label.KNOWN,
    "会": Label.KNOWN,
    "讀音": Label.READING_UNKNOWN,
    "读音": Label.READING_UNKNOWN,
    "念法": Label.READING_UNKNOWN,
    "發音": Label.READING_UNKNOWN,
    "发音": Label.READING_UNKNOWN,
    "意思": Label.MEANING_UNKNOWN,
    "意義": Label.MEANING_UNKNOWN,
    "意义": Label.MEANING_UNKNOWN,
    "完全": Label.NO_MEMORY,
    "沒印象": Label.NO_MEMORY,
    "没印象": Label.NO_MEMORY,
}


@dataclass(frozen=True)
class ParsedAddIntent:
    surface: str
    reading: str
    meaning_zh: str
    label: Label


class OllamaClient:
    def __init__(self, base_url: str, model: str, enabled: bool = True, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enabled = enabled
        self.timeout = timeout

    def parse_add_intent(self, text: str) -> ParsedAddIntent | None:
        heuristic = heuristic_parse_add_intent(text)
        if heuristic and heuristic.reading and heuristic.meaning_zh:
            return heuristic
        if not self.enabled:
            return heuristic

        prompt = (
            "你是日文單字資料輸入器。從使用者文字抽取要加入的日文單字。\n"
            "只回傳 JSON，不要解釋。格式："
            '{"surface":"日本語","reading":"かな","meaning_zh":"繁中意思","label":"known|reading_unknown|meaning_unknown|no_memory"}\n'
            "如果資訊不足，缺的欄位用空字串，但 label 仍要猜最合理。\n"
            f"使用者文字：{text}"
        )
        try:
            raw = self._generate(prompt)
        except (urllib.error.URLError, TimeoutError, OSError):
            return heuristic
        parsed = _json_from_text(raw)
        if not parsed or not parsed.get("surface"):
            return heuristic
        try:
            label = Label(parsed.get("label", "meaning_unknown"))
        except ValueError:
            label = guess_label(text)
        return ParsedAddIntent(
            surface=str(parsed.get("surface", "")).strip(),
            reading=str(parsed.get("reading", "")).strip(),
            meaning_zh=str(parsed.get("meaning_zh", "")).strip(),
            label=label,
        )

    def answer(self, text: str, context: str = "") -> str | None:
        if not self.enabled:
            return None
        prompt = (
            "你是使用者的日文 N3 單字複習 Discord 助手。"
            "用繁體中文回答，簡短、直接、有幫助。"
            "如果使用者問日文單字，請說明意思、讀音、常見用法。"
            "不要假裝你已經寫入資料庫，除非上下文說已寫入。\n"
            f"上下文：{context}\n"
            f"使用者：{text}"
        )
        try:
            return self._generate(prompt).strip() or None
        except (urllib.error.URLError, TimeoutError, OSError):
            return None

    def translate_dictionary_meaning(self, surface: str, reading: str, meaning: str) -> str:
        if not self.enabled:
            return f"中文翻譯暫時失敗；原始字典釋義：{meaning}"
        prompt = (
            "把下面日文字典的英文釋義整理成精簡繁體中文。"
            "只回傳意思本身，不要加前言。\n"
            f"單字：{surface}\n讀音：{reading}\n英文釋義：{meaning}"
        )
        try:
            translated = self._generate(prompt).strip()
        except (urllib.error.URLError, TimeoutError, OSError):
            return f"中文翻譯暫時失敗；原始字典釋義：{meaning}"
        return translated or f"中文翻譯暫時失敗；原始字典釋義：{meaning}"

    def example_sentence(self, surface: str, reading: str, meaning_zh: str) -> str:
        if not self.enabled:
            return "例句暫時無法產生，請確認 Ollama 是否正在執行。"
        prompt = (
            "請為下面日文單字產生一個 N3 程度的短句範例，並附繁體中文翻譯。"
            "格式固定為：例句：日本語。\\n中文：繁中翻譯。"
            "句子要自然、短，不要解釋。\n"
            f"單字：{surface}\n讀音：{reading}\n意思：{meaning_zh}"
        )
        try:
            generated = self._generate(prompt).strip()
        except (urllib.error.URLError, TimeoutError, OSError):
            return "例句暫時無法產生，請確認 Ollama 是否正在執行。"
        return generated or "例句暫時無法產生，請確認 Ollama 是否正在執行。"

    def _generate(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 320},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body.get("response", ""))


def heuristic_parse_add_intent(text: str) -> ParsedAddIntent | None:
    surface = _extract_quoted_word(text) or _extract_japanese_token(text)
    if not surface:
        return None
    reading = _extract_after(text, ["讀音", "读音", "reading", "念法"])
    meaning = _extract_after(text, ["意思", "meaning", "中文"])
    return ParsedAddIntent(
        surface=surface,
        reading=reading,
        meaning_zh=meaning,
        label=guess_label(text),
    )


def guess_label(text: str) -> Label:
    for key, label in LABEL_HINTS.items():
        if key in text:
            return label
    return Label.MEANING_UNKNOWN


def _extract_quoted_word(text: str) -> str:
    match = re.search(r"[「『\"]([^」』\"]+)[」』\"]", text)
    return match.group(1).strip() if match else ""


def _extract_japanese_token(text: str) -> str:
    matches = re.findall(r"[\u3040-\u30ff\u3400-\u9fff々〆〤]+", text)
    ignored = {"加入", "意思", "讀音", "读音", "完全", "印象", "看過", "看过"}
    for match in matches:
        if match not in ignored and len(match) >= 2:
            return match
    return ""


def _extract_after(text: str, keys: list[str]) -> str:
    for key in keys:
        match = re.search(rf"{re.escape(key)}[:： ]+([^,，。]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _json_from_text(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
