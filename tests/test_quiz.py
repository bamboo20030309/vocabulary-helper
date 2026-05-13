from __future__ import annotations

import random

from n3_discord_vocab.db import VocabularyStore
from n3_discord_vocab.models import CardType, Label, QuestionType
from n3_discord_vocab.quiz import QuizEngine, display_reading, has_kanji


def test_daily_quiz_builds_questions(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    store.seed_defaults()
    store.upsert_word(
        surface="締め切り",
        reading="しめきり",
        meaning_zh="截止、期限",
        label=Label.MEANING_UNKNOWN,
    )
    engine = QuizEngine(store, random.Random(1))

    questions = engine.build_daily_quiz(10)

    assert len(questions) == 10
    assert all(len(question.options) == 4 for question in questions)
    assert all(question.correct_answer in question.options for question in questions)
    assert sum(question.card_type == CardType.MEANING for question in questions) == 8
    assert sum(question.card_type == CardType.READING for question in questions) == 2


def test_reading_questions_only_use_kanji_words(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    store.upsert_word("敢えて", "あえて", "故意、刻意", Label.READING_UNKNOWN)
    store.upsert_word("やがて", "やがて", "不久、終於", Label.READING_UNKNOWN)
    store.upsert_word("承る", "うけたまわる", "聽取、承蒙", Label.READING_UNKNOWN)
    engine = QuizEngine(store, random.Random(1))

    questions = engine._questions_for_type(QuestionType.READING, 2, set())

    assert questions
    assert all(has_kanji(question.word.surface) for question in questions)


def test_focused_quiz_uses_seventy_percent_focus_words(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    focus_words = [
        store.upsert_word(f"新語{i}", f"しんご{i}", f"新詞{i}", Label.NO_MEMORY)
        for i in range(7)
    ]
    for i in range(5):
        store.upsert_word(f"旧語{i}", f"きゅうご{i}", f"舊詞{i}", Label.MEANING_UNKNOWN)
    engine = QuizEngine(store, random.Random(1))

    questions = engine.build_quiz_with_focus_words(focus_words, 10, 0.7)
    focus_ids = {word.id for word in focus_words}

    assert len(questions) == 10
    assert sum(question.word.id in focus_ids for question in questions) >= 7
    assert sum(question.card_type == CardType.MEANING for question in questions) == 8
    assert sum(question.card_type == CardType.READING for question in questions) == 2


def test_meaning_question_options_use_readings(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    word = store.upsert_word("締め切り", "しめきり", "截止、期限", Label.MEANING_UNKNOWN)
    store.upsert_word("結果", "けっか", "結果", Label.NO_MEMORY)
    store.upsert_word("原因", "げんいん", "原因", Label.NO_MEMORY)
    store.upsert_word("環境", "かんきょう", "環境", Label.NO_MEMORY)
    engine = QuizEngine(store, random.Random(1))

    question = engine.meaning_question(word, QuestionType.MEANING)
    readings = {display_reading(candidate) for candidate in store.all_words()}
    surfaces = {candidate.surface for candidate in store.all_words()}

    assert question.correct_answer == "しめきり"
    assert set(question.options) <= readings
    assert set(question.options).isdisjoint(surfaces)


def test_meaning_questions_use_varied_fallback_sentences(tmp_path):
    store = VocabularyStore(tmp_path / "vocab.sqlite3")
    words = [
        store.upsert_word("未知副詞", "みちふくし", "未知副詞", Label.NO_MEMORY, part_of_speech="adverb"),
        store.upsert_word("未知動詞", "みちどうし", "未知動詞", Label.NO_MEMORY, part_of_speech="verb"),
        store.upsert_word("未知名詞", "みちめいし", "未知名詞", Label.NO_MEMORY, part_of_speech="noun"),
    ]
    engine = QuizEngine(store, random.Random(1))

    prompts = [engine.meaning_question(word, QuestionType.MEANING).prompt for word in words]

    assert len(set(prompts)) > 1
    assert all("この文では____が一番自然です。" not in prompt for prompt in prompts)
