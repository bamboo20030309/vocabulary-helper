from __future__ import annotations

import random
import re

from .db import VocabularyStore
from .models import CardType, Label, QuestionType, QuizQuestion, Word


EXAMPLE_SENTENCES = {
    "慌てる": "電車が遅れて、朝から____てしまった。",
    "いきなり": "彼は____大きな声で話し始めた。",
    "やがて": "雨は____止むでしょう。",
    "ぼんやり": "疲れていて、窓の外を____見ていた。",
    "締め切り": "レポートの____は明日の午後五時です。",
    "承る": "ご意見を係の者が____ます。",
    "預ける": "旅行中、荷物を駅のロッカーに____。",
    "抱える": "彼女は大きな問題を____ている。",
    "勘違い": "時間を一時間早いと____していた。",
    "改めて": "詳しい予定は____連絡します。",
    "余計": "心配しすぎると、____疲れてしまう。",
    "案外": "この問題は____簡単だった。",
    "一応": "出かける前に、____天気を確認した。",
    "妙": "今日は彼の様子が少し____だ。",
    "徹夜": "試験前に____して勉強した。",
    "省く": "時間がないので、説明の一部を____。",
    "任せる": "この仕事は田中さんに____ことにした。",
    "悔しい": "あと一点で負けて、とても____。",
    "ずらす": "会議の時間を三十分____。",
    "わざと": "彼は____間違えたふりをした。",
}


class QuizEngine:
    def __init__(self, store: VocabularyStore, rng: random.Random | None = None):
        self.store = store
        self.rng = rng or random.Random()

    def build_daily_quiz(self, count: int = 10) -> list[QuizQuestion]:
        selected: list[QuizQuestion] = []
        used_ids: set[int] = set()

        plan = [
            (QuestionType.MEANING, 5),
            (QuestionType.READING, 2),
            (QuestionType.NEW_WORD, 2),
            (QuestionType.KNOWN_RECALL, 1),
        ]
        for question_type, planned_count in plan:
            for question in self._questions_for_type(question_type, planned_count, used_ids):
                selected.append(question)
                used_ids.add(question.word.id)

        while len(selected) < count:
            fallback = self._questions_for_type(QuestionType.MEANING, 1, used_ids)
            if not fallback:
                fallback = self._questions_for_type(QuestionType.NEW_WORD, 1, used_ids)
            if not fallback:
                break
            selected.extend(fallback)
            used_ids.add(fallback[0].word.id)

        self.rng.shuffle(selected)
        return selected[:count]

    def build_quiz_with_focus_words(
        self,
        focus_words: list[Word],
        count: int = 10,
        focus_ratio: float = 0.7,
    ) -> list[QuizQuestion]:
        selected: list[QuizQuestion] = []
        used_ids: set[int] = set()
        focus_count = min(len(focus_words), round(count * focus_ratio))
        for word in focus_words[:focus_count]:
            selected.append(self.meaning_question(word, QuestionType.NEW_WORD))
            used_ids.add(word.id)

        while len(selected) < count:
            fallback = self._questions_for_type(QuestionType.MEANING, 1, used_ids)
            if not fallback:
                fallback = self._questions_for_type(QuestionType.KNOWN_RECALL, 1, used_ids)
            if not fallback:
                break
            selected.extend(fallback)
            used_ids.add(fallback[0].word.id)

        self.rng.shuffle(selected)
        return selected[:count]

    def _questions_for_type(
        self,
        question_type: QuestionType,
        count: int,
        used_ids: set[int],
    ) -> list[QuizQuestion]:
        if question_type == QuestionType.MEANING:
            words = self.store.due_words(
                CardType.MEANING,
                [Label.MEANING_UNKNOWN, Label.NO_MEMORY],
                count,
                used_ids,
            )
            return [self.meaning_question(word, question_type) for word in words]

        if question_type == QuestionType.READING:
            words = self.store.due_words(
                CardType.READING,
                [Label.READING_UNKNOWN, Label.NO_MEMORY],
                count * 3,
                used_ids,
            )
            words = [word for word in words if has_kanji(word.surface)][:count]
            return [self.reading_question(word, question_type) for word in words]

        if question_type == QuestionType.KNOWN_RECALL:
            words = self.store.due_words(
                CardType.MEANING,
                [Label.KNOWN],
                count,
                used_ids,
            )
            return [self.meaning_question(word, question_type) for word in words]

        words = self.store.due_words(
            CardType.MEANING,
            [Label.NO_MEMORY],
            count,
            used_ids,
        )
        if len(words) < count:
            more = self.store.random_words(count - len(words), [*used_ids, *[w.id for w in words]])
            words.extend(more)
        return [self.meaning_question(word, question_type) for word in words]

    def meaning_question(self, word: Word, question_type: QuestionType) -> QuizQuestion:
        distractors = [
            candidate.surface
            for candidate in self.store.random_words(12, [word.id])
            if candidate.surface != word.surface
        ]
        options = self._options(word.surface, distractors)
        sentence = EXAMPLE_SENTENCES.get(word.surface, f"この文では____が一番自然です。")
        prompt = f"短句填空：{sentence}\n請選最適合填入空格的單字。"
        explanation = f"{word.surface} / {word.reading}：{word.meaning_zh}"
        return QuizQuestion(
            word=word,
            question_type=question_type,
            card_type=CardType.MEANING,
            prompt=prompt,
            options=options,
            correct_index=options.index(word.surface),
            explanation=explanation,
        )

    def reading_question(self, word: Word, question_type: QuestionType) -> QuizQuestion:
        distractors = [
            candidate.reading
            for candidate in self.store.random_words(12, [word.id])
            if candidate.reading != word.reading
        ]
        options = self._options(word.reading, distractors)
        prompt = f"「{word.surface}」的讀音是？"
        explanation = f"{word.surface} / {word.reading}：{word.meaning_zh}"
        return QuizQuestion(
            word=word,
            question_type=question_type,
            card_type=CardType.READING,
            prompt=prompt,
            options=options,
            correct_index=options.index(word.reading),
            explanation=explanation,
        )

    def _options(self, correct: str, distractors: list[str]) -> list[str]:
        unique = []
        for item in distractors:
            if item and item not in unique and item != correct:
                unique.append(item)
        fallback = ["不知道", "以上皆非", "容易混淆的用法"]
        for item in fallback:
            if len(unique) >= 3:
                break
            if item != correct and item not in unique:
                unique.append(item)
        options = [correct, *unique[:3]]
        self.rng.shuffle(options)
        return options


def has_kanji(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff々〆〤]", text))
