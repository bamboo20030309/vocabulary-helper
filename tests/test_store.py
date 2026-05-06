from __future__ import annotations

from n3_discord_vocab.db import VocabularyStore
from n3_discord_vocab.models import CardType, Label


def test_upsert_and_review_label_flow(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    word = store.upsert_word(
        surface="締め切り",
        reading="しめきり",
        meaning_zh="截止、期限",
        label=Label.MEANING_UNKNOWN,
    )

    due = store.due_words(CardType.MEANING, [Label.MEANING_UNKNOWN], 10)
    assert [item.surface for item in due] == ["締め切り"]

    first = store.record_review(
        word.id,
        CardType.MEANING,
        "meaning",
        "截止、期限",
        True,
    )
    assert first == Label.MEANING_UNKNOWN

    second = store.record_review(
        word.id,
        CardType.MEANING,
        "meaning",
        "截止、期限",
        True,
    )
    assert second == Label.MEANING_UNKNOWN

    third = store.record_review(
        word.id,
        CardType.MEANING,
        "meaning",
        "截止、期限",
        True,
    )
    assert third == Label.KNOWN


def test_wrong_reading_sets_reading_unknown(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    word = store.upsert_word(
        surface="承る",
        reading="うけたまわる",
        meaning_zh="聽取、承蒙、接受",
        label=Label.KNOWN,
    )

    label = store.record_review(
        word.id,
        CardType.READING,
        "reading",
        "ことわる",
        False,
    )

    assert label == Label.READING_UNKNOWN


def test_wrong_meaning_sets_meaning_unknown(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    word = store.upsert_word(
        surface="やがて",
        reading="やがて",
        meaning_zh="不久、終於",
        label=Label.KNOWN,
    )

    label = store.record_review(
        word.id,
        CardType.MEANING,
        "meaning",
        "いきなり",
        False,
    )

    assert label == Label.MEANING_UNKNOWN
