from __future__ import annotations

import random

from n3_discord_vocab.db import VocabularyStore
from n3_discord_vocab.models import Label
from n3_discord_vocab.quiz import QuizEngine


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
