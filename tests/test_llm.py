from __future__ import annotations

from n3_discord_vocab.llm import heuristic_parse_add_intent
from n3_discord_vocab.models import Label


def test_heuristic_parse_add_intent():
    parsed = heuristic_parse_add_intent("把「承る」加入，我看過但讀音不記得，讀音:うけたまわる，意思:聽取")

    assert parsed is not None
    assert parsed.surface == "承る"
    assert parsed.reading == "うけたまわる"
    assert parsed.meaning_zh == "聽取"
    assert parsed.label == Label.READING_UNKNOWN
