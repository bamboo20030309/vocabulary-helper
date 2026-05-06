from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Label(StrEnum):
    KNOWN = "known"
    READING_UNKNOWN = "reading_unknown"
    MEANING_UNKNOWN = "meaning_unknown"
    NO_MEMORY = "no_memory"


class CardType(StrEnum):
    MEANING = "meaning"
    READING = "reading"


class QuestionType(StrEnum):
    MEANING = "meaning"
    READING = "reading"
    NEW_WORD = "new_word"
    KNOWN_RECALL = "known_recall"


@dataclass(frozen=True)
class Word:
    id: int
    surface: str
    reading: str
    meaning_zh: str
    jlpt_level: str
    part_of_speech: str
    source: str


@dataclass(frozen=True)
class Card:
    word_id: int
    card_type: CardType
    label: Label
    due_at: str
    interval_days: int
    ease: float
    wrong_count: int
    correct_count: int


@dataclass(frozen=True)
class QuizQuestion:
    word: Word
    question_type: QuestionType
    card_type: CardType
    prompt: str
    options: list[str]
    correct_index: int
    explanation: str

    @property
    def correct_answer(self) -> str:
        return self.options[self.correct_index]
