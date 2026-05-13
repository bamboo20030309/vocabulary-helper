from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import CardType, Label, Word
from .seed_words import SEED_WORDS


UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


class VocabularyStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    surface TEXT NOT NULL UNIQUE,
                    reading TEXT NOT NULL,
                    meaning_zh TEXT NOT NULL,
                    jlpt_level TEXT NOT NULL DEFAULT 'N3',
                    part_of_speech TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cards (
                    word_id INTEGER NOT NULL,
                    card_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL DEFAULT 0,
                    ease REAL NOT NULL DEFAULT 2.3,
                    wrong_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    consecutive_correct INTEGER NOT NULL DEFAULT 0,
                    last_reviewed_at TEXT,
                    PRIMARY KEY (word_id, card_type),
                    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word_id INTEGER NOT NULL,
                    card_type TEXT NOT NULL,
                    question_type TEXT NOT NULL,
                    user_answer TEXT NOT NULL,
                    correct INTEGER NOT NULL,
                    old_label TEXT NOT NULL,
                    new_label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(conn, "cards", "consecutive_correct", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if column not in {row["name"] for row in rows}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def seed_defaults(self) -> None:
        for surface, reading, meaning, level, pos in SEED_WORDS:
            self.upsert_word(
                surface=surface,
                reading=reading,
                meaning_zh=meaning,
                label=Label.NO_MEMORY,
                jlpt_level=level,
                part_of_speech=pos,
                source="seed",
            )

    def upsert_word(
        self,
        surface: str,
        reading: str,
        meaning_zh: str,
        label: Label,
        jlpt_level: str = "N3",
        part_of_speech: str = "",
        source: str = "manual",
    ) -> Word:
        now = iso(utcnow())
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM words WHERE surface = ?", (surface,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE words
                    SET reading = ?, meaning_zh = ?, jlpt_level = ?, part_of_speech = ?
                    WHERE id = ?
                    """,
                    (reading, meaning_zh, jlpt_level, part_of_speech, existing["id"]),
                )
                word_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO words(surface, reading, meaning_zh, jlpt_level, part_of_speech, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (surface, reading, meaning_zh, jlpt_level, part_of_speech, source, now),
                )
                word_id = cur.lastrowid

            self._ensure_cards(conn, word_id, label)
            if label == Label.READING_UNKNOWN:
                self.set_label(word_id, CardType.READING, Label.READING_UNKNOWN, conn=conn)
            elif label == Label.MEANING_UNKNOWN:
                self.set_label(word_id, CardType.MEANING, Label.MEANING_UNKNOWN, conn=conn)
            elif label == Label.KNOWN:
                self.set_label(word_id, CardType.MEANING, Label.KNOWN, conn=conn)
                self.set_label(word_id, CardType.READING, Label.KNOWN, conn=conn)

        return self.get_word(surface)

    def _ensure_cards(self, conn: sqlite3.Connection, word_id: int, label: Label) -> None:
        now = iso(utcnow())
        for card_type in (CardType.MEANING, CardType.READING):
            card_label = label
            if label == Label.READING_UNKNOWN and card_type == CardType.MEANING:
                card_label = Label.KNOWN
            if label == Label.MEANING_UNKNOWN and card_type == CardType.READING:
                card_label = Label.KNOWN
            conn.execute(
                """
                INSERT OR IGNORE INTO cards(word_id, card_type, label, due_at)
                VALUES (?, ?, ?, ?)
                """,
                (word_id, card_type.value, card_label.value, now),
            )

    def get_word(self, surface: str) -> Word:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM words WHERE surface = ?", (surface,)).fetchone()
        if row is None:
            raise KeyError(surface)
        return self._row_to_word(row)

    def get_word_by_id(self, word_id: int) -> Word:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
        if row is None:
            raise KeyError(word_id)
        return self._row_to_word(row)

    def set_label(
        self,
        word_id: int,
        card_type: CardType,
        label: Label,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        due = iso(utcnow())
        sql = "UPDATE cards SET label = ?, due_at = ? WHERE word_id = ? AND card_type = ?"
        args = (label.value, due, word_id, card_type.value)
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.connect() as own_conn:
            own_conn.execute(sql, args)

    def postpone_word(self, word_id: int, days: int = 3) -> None:
        due = iso(utcnow() + timedelta(days=days))
        with self.connect() as conn:
            conn.execute("UPDATE cards SET due_at = ? WHERE word_id = ?", (due, word_id))

    def due_words(
        self,
        card_type: CardType,
        labels: Iterable[Label],
        limit: int,
        exclude_ids: Iterable[int] = (),
    ) -> list[Word]:
        label_values = [label.value for label in labels]
        excluded = list(exclude_ids)
        placeholders = ",".join("?" for _ in label_values)
        exclude_sql = ""
        now = utcnow()
        cooldown_cutoff = iso(now - timedelta(days=3))
        args: list[object] = [card_type.value, *label_values, iso(now), cooldown_cutoff]
        if excluded:
            exclude_sql = "AND w.id NOT IN (" + ",".join("?" for _ in excluded) + ")"
            args.extend(excluded)
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT w.*
                FROM words w
                JOIN cards c ON c.word_id = w.id
                WHERE c.card_type = ?
                  AND c.label IN ({placeholders})
                  AND c.due_at <= ?
                  AND NOT EXISTS (
                    SELECT 1
                    FROM reviews r
                    WHERE r.word_id = w.id
                      AND r.created_at >= ?
                  )
                  {exclude_sql}
                ORDER BY
                  CASE c.label
                    WHEN 'meaning_unknown' THEN 0
                    WHEN 'no_memory' THEN 1
                    WHEN 'reading_unknown' THEN 2
                    ELSE 3
                  END,
                  c.wrong_count DESC,
                  c.due_at ASC
                LIMIT ?
                """,
                args,
            ).fetchall()
        return [self._row_to_word(row) for row in rows]

    def random_words(self, limit: int, exclude_ids: Iterable[int] = ()) -> list[Word]:
        excluded = list(exclude_ids)
        exclude_sql = ""
        args: list[object] = []
        cooldown_cutoff = iso(utcnow() - timedelta(days=3))
        if excluded:
            exclude_sql = "WHERE id NOT IN (" + ",".join("?" for _ in excluded) + ")"
            args.extend(excluded)
        if exclude_sql:
            exclude_sql += """
              AND NOT EXISTS (
                SELECT 1 FROM reviews r
                WHERE r.word_id = words.id AND r.created_at >= ?
              )
            """
        else:
            exclude_sql = """
              WHERE NOT EXISTS (
                SELECT 1 FROM reviews r
                WHERE r.word_id = words.id AND r.created_at >= ?
              )
            """
        args.append(cooldown_cutoff)
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM words {exclude_sql} ORDER BY RANDOM() LIMIT ?",
                args,
            ).fetchall()
        return [self._row_to_word(row) for row in rows]

    def all_words(self) -> list[Word]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM words ORDER BY surface").fetchall()
        return [self._row_to_word(row) for row in rows]

    def list_words(self, label: Label | None = None, limit: int = 20) -> list[tuple[Word, str, str]]:
        args: list[object] = []
        label_sql = ""
        if label is not None:
            label_sql = "WHERE c.label = ?"
            args.append(label.value)
        args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT w.*,
                       MAX(CASE WHEN c.card_type = 'meaning' THEN c.label END) AS meaning_label,
                       MAX(CASE WHEN c.card_type = 'reading' THEN c.label END) AS reading_label
                FROM words w
                JOIN cards c ON c.word_id = w.id
                {label_sql}
                GROUP BY w.id
                ORDER BY w.created_at DESC, w.id DESC
                LIMIT ?
                """,
                args,
            ).fetchall()
        return [
            (self._row_to_word(row), row["meaning_label"] or "", row["reading_label"] or "")
            for row in rows
        ]

    def record_review(
        self,
        word_id: int,
        card_type: CardType,
        question_type: str,
        user_answer: str,
        correct: bool,
    ) -> Label:
        now = utcnow()
        with self.connect() as conn:
            card = conn.execute(
                "SELECT * FROM cards WHERE word_id = ? AND card_type = ?",
                (word_id, card_type.value),
            ).fetchone()
            if card is None:
                raise KeyError((word_id, card_type))
            old_label = Label(card["label"])
            new_consecutive = card["consecutive_correct"] + 1 if correct else 0
            new_label = next_label(old_label, card_type, correct, new_consecutive)
            interval = next_interval_days(new_label, correct, card["interval_days"], card["ease"])
            ease = max(1.3, card["ease"] + (0.12 if correct else -0.2))
            due = now + timedelta(days=interval)
            conn.execute(
                """
                UPDATE cards
                SET label = ?, due_at = ?, interval_days = ?, ease = ?,
                    wrong_count = wrong_count + ?,
                    correct_count = correct_count + ?,
                    consecutive_correct = ?,
                    last_reviewed_at = ?
                WHERE word_id = ? AND card_type = ?
                """,
                (
                    new_label.value,
                    iso(due),
                    interval,
                    ease,
                    0 if correct else 1,
                    1 if correct else 0,
                    new_consecutive,
                    iso(now),
                    word_id,
                    card_type.value,
                ),
            )
            conn.execute(
                """
                INSERT INTO reviews(word_id, card_type, question_type, user_answer, correct,
                                    old_label, new_label, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    word_id,
                    card_type.value,
                    question_type,
                    user_answer,
                    int(correct),
                    old_label.value,
                    new_label.value,
                    iso(now),
                ),
            )
        return new_label

    def stats(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT label, COUNT(*) AS n FROM cards GROUP BY label"
            ).fetchall()
            total_words = conn.execute("SELECT COUNT(*) AS n FROM words").fetchone()["n"]
            reviews = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
        result = {row["label"]: row["n"] for row in rows}
        result["words"] = total_words
        result["reviews"] = reviews
        return result

    @staticmethod
    def _row_to_word(row: sqlite3.Row) -> Word:
        return Word(
            id=row["id"],
            surface=row["surface"],
            reading=row["reading"],
            meaning_zh=row["meaning_zh"],
            jlpt_level=row["jlpt_level"],
            part_of_speech=row["part_of_speech"],
            source=row["source"],
        )


def next_label(old: Label, card_type: CardType, correct: bool, consecutive_correct: int) -> Label:
    if not correct:
        if card_type == CardType.READING:
            return Label.READING_UNKNOWN
        return Label.MEANING_UNKNOWN

    threshold = 2 if old == Label.NO_MEMORY else 3
    if consecutive_correct >= threshold:
        return Label.KNOWN
    return old


def next_interval_days(label: Label, correct: bool, current_interval: int, ease: float) -> int:
    if not correct:
        return 3
    if label == Label.NO_MEMORY:
        return 3
    if label in {Label.MEANING_UNKNOWN, Label.READING_UNKNOWN}:
        return 3
    if current_interval <= 0:
        return 3
    return max(3, round(current_interval * ease))
