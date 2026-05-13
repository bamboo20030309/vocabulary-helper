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
    "せめて": "忙しくても、____朝ご飯だけは食べたい。",
    "むしろ": "安い物より、____長く使える物を選びたい。",
    "なかなか": "この問題は____答えが出なかった。",
    "すっかり": "雨にぬれて、服が____重くなった。",
    "なるべく": "健康のために、____歩くようにしている。",
    "たびたび": "彼は仕事で京都を____訪れている。",
    "ついでに": "駅へ行く____、郵便局にも寄った。",
    "余る": "料理を作りすぎて、ご飯が少し____。",
    "支える": "家族の言葉が、つらい時の私を____。",
    "断る": "都合が悪かったので、友だちの誘いを____。",
    "眺める": "休みの日は、海を____のが好きだ。",
    "通じる": "この道は駅まで____。",
    "試す": "新しい勉強方法を一度____ことにした。",
    "失う": "大切な資料を____て、とても困った。",
    "避ける": "混雑を____ために、早めに家を出た。",
    "比べる": "二つの案を____てから決めよう。",
    "似合う": "その明るい色の服は君によく____。",
    "積極的": "彼女は授業で____に質問する。",
    "消極的": "彼は新しい計画に少し____だった。",
    "貴重": "旅先で____な経験をした。",
    "平等": "みんなが____に意見を言える場を作りたい。",
    "迷惑": "夜遅くに大きな音を出すのは____だ。",
    "苦労": "一人暮らしを始めて、お金の管理に____した。",
    "環境": "静かな____で勉強すると集中しやすい。",
    "状態": "スマホの電池が少ない____で出かけた。",
    "原因": "失敗の____を落ち着いて考えた。",
    "結果": "努力した____、試験に合格できた。",
}


FALLBACK_SENTENCE_PATTERNS = {
    "adverb": [
        "大事な時ほど、____行動したほうがいい。",
        "彼は理由を聞いて、____納得したようだった。",
        "時間がないので、今日は____先に進めよう。",
    ],
    "verb": [
        "困った時は、一度____ことも必要だ。",
        "先生に相談してから、次の方法を____。",
        "この仕事を最後まで____のは簡単ではない。",
    ],
    "i-adjective": [
        "その一言を聞いて、とても____気持ちになった。",
        "思ったより____結果になって驚いた。",
        "今日は少し____ので、早めに休みたい。",
    ],
    "na-adjective": [
        "会議では____な意見も必要だ。",
        "その説明は少し____で、すぐには分からなかった。",
        "彼の考え方はとても____だと思う。",
    ],
    "noun": [
        "まず____を確認してから始めよう。",
        "この問題では____がとても大切だ。",
        "話し合いの中で、____について意見が出た。",
    ],
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
        candidates = [
            candidate
            for candidate in self.store.random_words(12, [word.id])
            if candidate.surface != word.surface
        ]
        distractors = [candidate.surface for candidate in candidates]
        options = self._options(word.surface, distractors)
        sentence = self.meaning_sentence(word)
        prompt = f"短句填空：{sentence}\n請選最適合填入空格的單字。"
        explanation = f"{word.surface} / {word.reading}：{word.meaning_zh}"
        option_explanations = {word.surface: word.meaning_zh}
        option_explanations.update({candidate.surface: candidate.meaning_zh for candidate in candidates})
        return QuizQuestion(
            word=word,
            question_type=question_type,
            card_type=CardType.MEANING,
            prompt=prompt,
            options=options,
            correct_index=options.index(word.surface),
            explanation=explanation,
            option_explanations=option_explanations,
        )

    def meaning_sentence(self, word: Word) -> str:
        if word.surface in EXAMPLE_SENTENCES:
            return EXAMPLE_SENTENCES[word.surface]
        part = word.part_of_speech.lower()
        if "adverb" in part:
            patterns = FALLBACK_SENTENCE_PATTERNS["adverb"]
        elif "verb" in part:
            patterns = FALLBACK_SENTENCE_PATTERNS["verb"]
        elif "i-adjective" in part:
            patterns = FALLBACK_SENTENCE_PATTERNS["i-adjective"]
        elif "na-adjective" in part or "adjective" in part:
            patterns = FALLBACK_SENTENCE_PATTERNS["na-adjective"]
        elif "noun" in part:
            patterns = FALLBACK_SENTENCE_PATTERNS["noun"]
        else:
            patterns = [
                sentence
                for group in FALLBACK_SENTENCE_PATTERNS.values()
                for sentence in group
            ]
        return self.rng.choice(patterns)

    def reading_question(self, word: Word, question_type: QuestionType) -> QuizQuestion:
        candidates = [
            candidate
            for candidate in self.store.random_words(12, [word.id])
            if candidate.reading != word.reading
        ]
        distractors = [candidate.reading for candidate in candidates]
        options = self._options(word.reading, distractors)
        prompt = f"「{word.surface}」的讀音是？"
        explanation = f"{word.surface} / {word.reading}：{word.meaning_zh}"
        option_explanations = {word.reading: word.meaning_zh}
        option_explanations.update({candidate.reading: candidate.meaning_zh for candidate in candidates})
        return QuizQuestion(
            word=word,
            question_type=question_type,
            card_type=CardType.READING,
            prompt=prompt,
            options=options,
            correct_index=options.index(word.reading),
            explanation=explanation,
            option_explanations=option_explanations,
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
