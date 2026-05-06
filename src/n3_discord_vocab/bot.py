from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import Settings, load_settings
from .db import VocabularyStore
from .dictionary import DictionaryClient
from .llm import OllamaClient
from .models import CardType, Label, QuizQuestion
from .quiz import QuizEngine


LABEL_NAMES = {
    "known": "會的",
    "reading_unknown": "看過但讀音不記得",
    "meaning_unknown": "看過但意思不記得",
    "no_memory": "完全沒印象",
}


@dataclass
class QuizSession:
    questions: list[QuizQuestion]
    index: int = 0
    correct_count: int = 0

    @property
    def current(self) -> QuizQuestion:
        return self.questions[self.index]


class AnswerView(discord.ui.View):
    def __init__(self, app: VocabBot, session: QuizSession, user_id: int | None):
        super().__init__(timeout=900)
        self.app = app
        self.session = session
        self.user_id = user_id
        for i, option in enumerate(session.current.options):
            self.add_item(AnswerButton(i, option))


class AnswerButton(discord.ui.Button):
    def __init__(self, index: int, label: str):
        super().__init__(label=f"{chr(65 + index)}. {label}", style=discord.ButtonStyle.secondary)
        self.answer_index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AnswerView):
            return
        if view.user_id and interaction.user.id != view.user_id:
            await interaction.response.send_message("這組題目不是出給你的。", ephemeral=True)
            return

        question = view.session.current
        correct = self.answer_index == question.correct_index
        selected = question.options[self.answer_index]
        new_label = view.app.store.record_review(
            question.word.id,
            question.card_type,
            question.question_type.value,
            selected,
            correct,
        )
        if correct:
            view.session.correct_count += 1

        result = "答對了" if correct else f"答錯了，正解是 {question.correct_answer}"
        feedback = (
            f"{result}\n"
            f"{question.explanation}\n"
            f"目前標籤：{LABEL_NAMES[new_label.value]}"
        )
        view.session.index += 1

        if view.session.index >= len(view.session.questions):
            total = len(view.session.questions)
            await interaction.response.edit_message(
                content=(
                    f"{feedback}\n\n"
                    f"今天這組完成：{view.session.correct_count}/{total} 題。"
                ),
                view=None,
            )
            return

        next_question = view.session.current
        next_view = AnswerView(view.app, view.session, view.user_id)
        await interaction.response.edit_message(
            content=f"{feedback}\n\n{format_question(next_question, view.session.index, len(view.session.questions))}",
            view=next_view,
        )


class VocabBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = settings.message_content_intent
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.store = VocabularyStore(settings.database_path)
        self.store.seed_defaults()
        self.quiz_engine = QuizEngine(self.store)
        self.llm = OllamaClient(
            settings.ollama_url,
            settings.ollama_model,
            settings.llm_enabled,
            settings.ollama_timeout,
        )
        self.dictionary = DictionaryClient(settings.dictionary_enabled)
        self.last_daily_quiz_date: str | None = None

    async def setup_hook(self) -> None:
        self.tree.add_command(add_word)
        self.tree.add_command(mark_word)
        self.tree.add_command(quiz_now)
        self.tree.add_command(stats)
        self.tree.add_command(words)
        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to guild {self.settings.discord_guild_id}")
        else:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} global commands")
        self.daily_quiz_loop.start()

    async def on_ready(self) -> None:
        if self.user:
            print(f"Logged in as {self.user} ({self.user.id})")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if self.settings.discord_user_id and message.author.id != self.settings.discord_user_id:
            return
        if await self.handle_text_command(message):
            return
        handled = await self.handle_natural_message(message)
        if handled:
            return

    async def handle_text_command(self, message: discord.Message) -> bool:
        content = message.content.strip()
        if not content.startswith("!"):
            return False
        command, *parts = content.split()
        command = command.lower()

        if command == "!stats":
            await message.reply(format_stats(self.store.stats()))
            return True

        if command == "!words":
            limit = 20
            if parts and parts[0].isdigit():
                limit = max(1, min(50, int(parts[0])))
            rows = self.store.list_words(limit=limit)
            await message.reply(format_words(rows))
            return True

        if command == "!quiz":
            questions = self.quiz_engine.build_daily_quiz(10)
            if not questions:
                await message.reply("目前還沒有足夠單字可以出題。")
                return True
            session = QuizSession(questions)
            await message.reply(
                format_question(session.current, 0, len(questions)),
                view=AnswerView(self, session, message.author.id),
            )
            return True

        return False

    async def handle_natural_message(self, message: discord.Message) -> bool:
        parsed = await asyncio.to_thread(self.llm.parse_add_intent, message.content)
        should_add = parsed and any(
            key in message.content for key in ["加入", "新增", "記", "存", "不記得", "忘"]
        )
        if parsed and should_add:
            reading = parsed.reading
            meaning = parsed.meaning_zh
            part_of_speech = ""
            source = "llm"
            if not reading or not meaning:
                entry = await asyncio.to_thread(self.dictionary.lookup, parsed.surface)
                if entry:
                    reading = reading or entry.reading
                    meaning = meaning or await asyncio.to_thread(
                        self.llm.translate_dictionary_meaning,
                        entry.surface,
                        entry.reading,
                        entry.meaning,
                    )
                    part_of_speech = entry.part_of_speech
                    source = entry.source
            if not reading or not meaning:
                await message.reply("我抓到你想加入單字，但字典查不到完整資料。你可以補讀音或意思給我。")
                return True
            word = self.store.upsert_word(
                surface=parsed.surface,
                reading=reading,
                meaning_zh=meaning,
                label=parsed.label,
                part_of_speech=part_of_speech,
                source=source,
            )
            example = await asyncio.to_thread(
                self.llm.example_sentence,
                word.surface,
                word.reading,
                word.meaning_zh,
            )
            await message.reply(
                f"已加入：{word.surface} / {word.reading}：{word.meaning_zh}\n"
                f"標籤：{LABEL_NAMES[parsed.label.value]}\n"
                f"{example}"
            )
            return True

        keyword = parsed.surface if parsed else ""
        if keyword and any(key in message.content for key in ["意思", "讀音", "读音", "怎麼念", "怎么念"]):
            entry = await asyncio.to_thread(self.dictionary.lookup, keyword)
            if entry:
                meaning = await asyncio.to_thread(
                    self.llm.translate_dictionary_meaning,
                    entry.surface,
                    entry.reading,
                    entry.meaning,
                )
                example = await asyncio.to_thread(
                    self.llm.example_sentence,
                    entry.surface,
                    entry.reading,
                    meaning,
                )
                await message.reply(f"{entry.surface} / {entry.reading}：{meaning}\n{example}")
                return True

        answer = await asyncio.to_thread(self.llm.answer, message.content)
        if answer:
            await message.reply(answer)
            return True
        return False

    @tasks.loop(minutes=1)
    async def daily_quiz_loop(self) -> None:
        tz = ZoneInfo(self.settings.timezone)
        now = datetime.now(tz)
        if now.strftime("%H:%M") != self.settings.quiz_time:
            return
        today = now.strftime("%Y-%m-%d")
        if self.last_daily_quiz_date == today:
            return
        channel = await self.daily_target_channel()
        if channel is None:
            return
        questions = self.quiz_engine.build_daily_quiz(10)
        if not questions:
            await channel.send("今天還沒有足夠單字可以出題，先用 `/add` 加幾個。")
            self.last_daily_quiz_date = today
            return
        session = QuizSession(questions)
        await channel.send(
            "早安，今天 10 題。\n\n" + format_question(session.current, 0, len(questions)),
            view=AnswerView(self, session, self.settings.discord_user_id),
        )
        self.last_daily_quiz_date = today

    @daily_quiz_loop.before_loop
    async def before_daily_quiz_loop(self) -> None:
        await self.wait_until_ready()

    async def daily_target_channel(
        self,
    ) -> discord.TextChannel | discord.DMChannel | discord.Thread | None:
        if self.settings.discord_channel_id:
            channel = self.get_channel(self.settings.discord_channel_id)
            if channel is None:
                channel = await self.fetch_channel(self.settings.discord_channel_id)
            if isinstance(channel, (discord.TextChannel, discord.DMChannel, discord.Thread)):
                return channel
            return None

        if not self.settings.discord_user_id:
            return None
        user = self.get_user(self.settings.discord_user_id)
        if user is None:
            user = await self.fetch_user(self.settings.discord_user_id)
        return await user.create_dm()


def label_choices() -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name="會的", value=Label.KNOWN.value),
        app_commands.Choice(name="看過但讀音不記得", value=Label.READING_UNKNOWN.value),
        app_commands.Choice(name="看過但意思不記得", value=Label.MEANING_UNKNOWN.value),
        app_commands.Choice(name="完全沒印象", value=Label.NO_MEMORY.value),
    ]


@app_commands.command(name="add", description="加入或更新一個日文單字")
@app_commands.describe(word="日文單字", reading="讀音", meaning="中文意思", label="目前記憶狀態")
@app_commands.choices(label=label_choices())
async def add_word(
    interaction: discord.Interaction,
    word: str,
    reading: str,
    meaning: str,
    label: app_commands.Choice[str],
) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    saved = bot.store.upsert_word(
        surface=word.strip(),
        reading=reading.strip(),
        meaning_zh=meaning.strip(),
        label=Label(label.value),
    )
    await interaction.response.send_message(
        f"已加入：{saved.surface} / {saved.reading}：{saved.meaning_zh}\n"
        f"標籤：{LABEL_NAMES[label.value]}"
    )


@app_commands.command(name="mark", description="手動調整單字標籤")
@app_commands.describe(word="日文單字", label="新的記憶狀態")
@app_commands.choices(label=label_choices())
async def mark_word(
    interaction: discord.Interaction,
    word: str,
    label: app_commands.Choice[str],
) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    try:
        saved = bot.store.get_word(word.strip())
    except KeyError:
        await interaction.response.send_message("找不到這個單字。", ephemeral=True)
        return
    target_label = Label(label.value)
    if target_label == Label.READING_UNKNOWN:
        bot.store.set_label(saved.id, CardType.READING, target_label)
    elif target_label == Label.MEANING_UNKNOWN:
        bot.store.set_label(saved.id, CardType.MEANING, target_label)
    else:
        bot.store.set_label(saved.id, CardType.READING, target_label)
        bot.store.set_label(saved.id, CardType.MEANING, target_label)
    await interaction.response.send_message(f"{saved.surface} 已標記為：{LABEL_NAMES[label.value]}")


@app_commands.command(name="quiz", description="立刻開始一組 10 題測驗")
async def quiz_now(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    questions = bot.quiz_engine.build_daily_quiz(10)
    if not questions:
        await interaction.response.send_message("目前還沒有足夠單字可以出題。", ephemeral=True)
        return
    session = QuizSession(questions)
    await interaction.response.send_message(
        format_question(session.current, 0, len(questions)),
        view=AnswerView(bot, session, interaction.user.id),
    )


@app_commands.command(name="stats", description="查看目前單字與答題統計")
async def stats(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    await interaction.response.send_message(format_stats(bot.store.stats()))


@app_commands.command(name="words", description="查看目前單字庫")
@app_commands.describe(label="只顯示某個標籤的單字", limit="最多顯示幾個，預設 20")
@app_commands.choices(label=label_choices())
async def words(
    interaction: discord.Interaction,
    label: app_commands.Choice[str] | None = None,
    limit: app_commands.Range[int, 1, 50] = 20,
) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    target_label = Label(label.value) if label else None
    rows = bot.store.list_words(target_label, limit)
    if not rows:
        await interaction.response.send_message("目前沒有符合條件的單字。", ephemeral=True)
        return
    await interaction.response.send_message(format_words(rows))


def format_words(rows: list[tuple[object, str, str]]) -> str:
    if not rows:
        return "目前沒有符合條件的單字。"
    lines = [f"單字庫最近 {len(rows)} 筆："]
    for word, meaning_label, reading_label in rows:
        meaning_name = LABEL_NAMES.get(meaning_label, meaning_label)
        reading_name = LABEL_NAMES.get(reading_label, reading_label)
        lines.append(
            f"- {word.surface} / {word.reading}：{word.meaning_zh} "
            f"[意思:{meaning_name}｜讀音:{reading_name}]"
        )
    return "\n".join(lines)


def format_stats(data: dict[str, int]) -> str:
    return "\n".join(
        [
            f"單字數：{data.get('words', 0)}",
            f"答題紀錄：{data.get('reviews', 0)}",
            f"會的卡片：{data.get('known', 0)}",
            f"讀音不記得：{data.get('reading_unknown', 0)}",
            f"意思不記得：{data.get('meaning_unknown', 0)}",
            f"完全沒印象：{data.get('no_memory', 0)}",
        ]
    )


def format_question(question: QuizQuestion, index: int, total: int) -> str:
    lines = [f"第 {index + 1} 題 / {total}", question.prompt]
    for i, option in enumerate(question.options):
        lines.append(f"{chr(65 + i)}. {option}")
    return "\n".join(lines)


def main() -> None:
    settings = load_settings()
    if not settings.discord_token:
        raise SystemExit("請先在 .env 設定 DISCORD_TOKEN。")
    bot = VocabBot(settings)
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
