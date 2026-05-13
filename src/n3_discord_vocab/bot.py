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
from .dictionary import DictionaryClient, DictionaryEntry
from .llm import OllamaClient
from .models import CardType, Label, QuizQuestion
from .quiz import QuizEngine, has_kanji


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
    history: list[str] | None = None

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
        self.add_item(QuitQuizButton())


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

        feedback = format_answer_feedback(
            question=question,
            index=view.session.index,
            selected=selected,
            correct=correct,
            new_label=new_label,
        )
        if view.session.history is None:
            view.session.history = []
        view.session.history.append(feedback)
        view.session.index += 1

        if view.session.index >= len(view.session.questions):
            total = len(view.session.questions)
            await interaction.response.edit_message(
                content=(
                    f"{format_quiz_history(view.session)}\n\n"
                    f"今天這組完成：{view.session.correct_count}/{total} 題。"
                ),
                view=None,
            )
            return

        next_question = view.session.current
        next_view = AnswerView(view.app, view.session, view.user_id)
        await interaction.response.edit_message(
            content=format_quiz_message(view.session),
            view=next_view,
        )


class QuitQuizButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="退出測驗", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AnswerView):
            return
        if view.user_id and interaction.user.id != view.user_id:
            await interaction.response.send_message("這組題目不是出給你的。", ephemeral=True)
            return
        total_answered = view.session.index
        content = format_quiz_history(view.session)
        if content:
            content += "\n\n"
        content += f"已退出測驗。目前答對：{view.session.correct_count}/{total_answered} 題。"
        await interaction.response.edit_message(content=content, view=None)


class NewWordSelectionView(discord.ui.View):
    def __init__(self, app: VocabBot, entries: list[DictionaryEntry], user_id: int | None):
        super().__init__(timeout=3600)
        self.app = app
        self.entries = entries
        self.user_id = user_id
        self.unknown_surfaces: set[str] = set()
        self.add_item(NewWordUnknownSelect(entries))
        self.add_item(NewWordDoneButton())


class NewWordUnknownSelect(discord.ui.Select):
    def __init__(self, entries: list[DictionaryEntry]):
        options = [
            discord.SelectOption(
                label=f"{entry.surface} / {entry.reading}",
                value=entry.surface,
                description=entry.meaning[:90],
            )
            for entry in entries
        ]
        super().__init__(
            placeholder="勾選不會的新單字；沒勾就是會",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, NewWordSelectionView):
            return
        if view.user_id and interaction.user.id != view.user_id:
            await interaction.response.send_message("這組新單字不是出給你的。", ephemeral=True)
            return
        view.unknown_surfaces = set(self.values)
        await interaction.response.defer()


class NewWordDoneButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="完成，開始今天題目", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, NewWordSelectionView):
            return
        if view.user_id and interaction.user.id != view.user_id:
            await interaction.response.send_message("這組新單字不是出給你的。", ephemeral=True)
            return

        meaning_unknown = []
        reading_unknown = []
        known = []
        focus_words = []
        for entry in view.entries:
            unknown_selected = entry.surface in view.unknown_surfaces
            if unknown_selected:
                label = Label.MEANING_UNKNOWN
            else:
                label = Label.KNOWN
            word = view.app.store.upsert_word(
                surface=entry.surface,
                reading=entry.reading,
                meaning_zh=entry.meaning,
                label=label,
                part_of_speech=entry.part_of_speech,
                source=entry.source,
            )
            if unknown_selected:
                focus_words.append(word)
                meaning_unknown.append(entry.surface)
                if has_kanji(entry.surface):
                    view.app.store.set_label(word.id, CardType.READING, Label.READING_UNKNOWN)
                    reading_unknown.append(entry.surface)
            else:
                view.app.store.postpone_word(word.id, days=3)
                known.append(entry.surface)

        summary = (
            f"新單字已記錄：{len(meaning_unknown)} 個不會，{len(known)} 個先標成會的。\n"
            f"不會：{', '.join(meaning_unknown) if meaning_unknown else '無'}"
        )
        await interaction.response.edit_message(content=summary, view=None)
        await view.app.send_quiz(
            interaction.channel,
            view.user_id,
            prefix="今天 10 題開始。會優先從剛剛標成不會的新單字出填空題。",
            focus_words=focus_words,
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
        self.tree.add_command(lookup)
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

        if command in {"!lookup", "!查"}:
            if not parts:
                await message.reply("請在 `!lookup` 後面接日文單字，例如：`!lookup 敢えて`")
                return True
            await message.reply(await self.lookup_word(" ".join(parts)))
            return True

        if command == "!add":
            if not parts:
                await message.reply("請在 `!add` 後面接日文單字，例如：`!add やがて`")
                return True
            saved, response = await self.complete_and_save_word(
                surface=" ".join(parts),
                label=Label.MEANING_UNKNOWN,
            )
            await message.reply(response)
            return True

        if command == "!quiz":
            await self.start_quiz_flow(message.channel, message.author.id, prefix="手動測驗開始。")
            return True

        return False

    async def handle_natural_message(self, message: discord.Message) -> bool:
        parsed = await asyncio.to_thread(self.llm.parse_add_intent, message.content)
        should_add = parsed and any(
            key in message.content.lower()
            for key in ["加入", "新增", "記", "存", "不記得", "忘", "add"]
        )
        if parsed and should_add:
            _word, response = await self.complete_and_save_word(
                surface=parsed.surface,
                label=parsed.label,
                reading=parsed.reading,
                meaning=parsed.meaning_zh,
            )
            await message.reply(response)
            return True

        keyword = parsed.surface if parsed else ""
        if keyword and any(key in message.content for key in ["意思", "讀音", "读音", "怎麼念", "怎么念"]):
            await message.reply(await self.lookup_word(keyword))
            return True

        answer = await asyncio.to_thread(self.llm.answer, message.content)
        if answer:
            await message.reply(answer)
            return True
        return False

    async def lookup_word(self, keyword: str) -> str:
        keyword = keyword.strip()
        if not keyword:
            return "請給我要查的日文單字。"
        entry = await asyncio.to_thread(self.dictionary.lookup, keyword)
        if not entry:
            return "查不到這個單字。"
        meaning = entry.meaning
        if entry.meaning_language != "zh":
            meaning = await asyncio.to_thread(
                self.llm.translate_dictionary_meaning,
                entry.surface,
                entry.reading,
                entry.meaning,
            )
        example = await asyncio.to_thread(
            self.example_for_entry,
            entry,
            meaning,
        )
        return f"{entry.surface} / {entry.reading}：{meaning}\n{example}"

    def example_for_entry(self, entry: DictionaryEntry, meaning: str) -> str:
        if entry.examples:
            japanese, chinese = entry.examples[0]
            return f"例句：{japanese}\n中文：{chinese}"
        return self.llm.example_sentence(entry.surface, entry.reading, meaning)

    async def complete_and_save_word(
        self,
        surface: str,
        label: Label,
        reading: str = "",
        meaning: str = "",
    ) -> tuple[object | None, str]:
        surface = surface.strip()
        reading = reading.strip()
        meaning = meaning.strip()
        if not surface:
            return None, "請給我要加入的日文單字。"

        part_of_speech = ""
        source = "manual"
        entry = await asyncio.to_thread(self.dictionary.lookup, surface)
        if entry:
            surface = entry.surface or surface
            reading = reading or entry.reading
            if not meaning:
                meaning = entry.meaning
                if entry.meaning_language != "zh":
                    meaning = await asyncio.to_thread(
                        self.llm.translate_dictionary_meaning,
                        entry.surface,
                        entry.reading,
                        entry.meaning,
                    )
            part_of_speech = entry.part_of_speech
            source = entry.source

        if not reading or not meaning:
            return (
                None,
                "我查不到完整資料。你可以補成：`!add 單字 讀音:かな 意思:中文意思`，"
                "或改用 `/add` 手動填讀音和意思。",
            )

        word = self.store.upsert_word(
            surface=surface,
            reading=reading,
            meaning_zh=meaning,
            label=label,
            part_of_speech=part_of_speech,
            source=source,
        )
        example = await asyncio.to_thread(
            self.example_for_entry,
            entry,
            word.meaning_zh,
        ) if entry else await asyncio.to_thread(
            self.llm.example_sentence,
            word.surface,
            word.reading,
            word.meaning_zh,
        )
        return (
            word,
            f"已加入：{word.surface} / {word.reading}：{word.meaning_zh}\n"
            f"標籤：{LABEL_NAMES[label.value]}\n"
            f"{example}",
        )

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
        preview_entries = self.new_word_preview_entries(10)
        if preview_entries:
            await channel.send(
                "開始今天題目前，先看 10 個新單字。\n"
                "請勾選不會的新單字；沒勾的會直接標成「會的」。"
                "勾選的漢字詞也會一起排進讀音複習。",
                view=NewWordSelectionView(self, preview_entries, self.settings.discord_user_id),
            )
            self.last_daily_quiz_date = today
            return
        await self.send_quiz(channel, self.settings.discord_user_id, prefix="早安，今天 10 題。")
        self.last_daily_quiz_date = today

    async def start_quiz_flow(
        self,
        channel: discord.abc.Messageable | None,
        user_id: int | None,
        prefix: str,
    ) -> None:
        if channel is None:
            return
        preview_entries = self.new_word_preview_entries(10)
        if preview_entries:
            await channel.send(
                f"{prefix}\n開始測驗前，先看 10 個新單字。\n"
                "請勾選不會的新單字；沒勾的會直接標成「會的」。"
                "勾選的漢字詞也會一起排進讀音複習。",
                view=NewWordSelectionView(self, preview_entries, user_id),
            )
            return
        await self.send_quiz(channel, user_id, prefix=prefix)

    async def send_quiz(
        self,
        channel: discord.abc.Messageable | None,
        user_id: int | None,
        prefix: str,
        focus_words: list | None = None,
    ) -> None:
        if channel is None:
            return
        if focus_words:
            questions = self.quiz_engine.build_quiz_with_focus_words(focus_words, 10, 0.7)
        else:
            questions = self.quiz_engine.build_daily_quiz(10)
        if not questions:
            await channel.send("今天還沒有足夠單字可以出題，先用 `/add` 加幾個。")
            return
        session = QuizSession(questions)
        await channel.send(
            f"{prefix}\n\n" + format_quiz_message(session),
            view=AnswerView(self, session, user_id),
        )

    def new_word_preview_entries(self, limit: int) -> list[DictionaryEntry]:
        known_surfaces = {word.surface for word in self.store.all_words()}
        known_readings = {word.reading for word in self.store.all_words()}
        entries = []
        for entry in self.dictionary.new_word_candidates():
            if entry.surface in known_surfaces or entry.reading in known_readings:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        return entries

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
@app_commands.describe(
    word="日文單字；只填這個也可以，bot 會自動查讀音和意思",
    reading="讀音，可留空",
    meaning="中文意思，可留空",
    label="目前記憶狀態，預設為看過但意思不記得",
)
@app_commands.choices(label=label_choices())
async def add_word(
    interaction: discord.Interaction,
    word: str,
    reading: str = "",
    meaning: str = "",
    label: app_commands.Choice[str] | None = None,
) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    await interaction.response.defer(thinking=True)
    target_label = Label(label.value) if label else Label.MEANING_UNKNOWN
    _saved, response = await bot.complete_and_save_word(
        surface=word,
        label=target_label,
        reading=reading,
        meaning=meaning,
    )
    await interaction.followup.send(response)


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
    await interaction.response.defer(thinking=True)
    await bot.start_quiz_flow(interaction.channel, interaction.user.id, prefix="手動測驗開始。")
    await interaction.followup.send("已建立測驗流程。", ephemeral=True)


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


@app_commands.command(name="lookup", description="查詢日文單字，不寫入單字庫")
@app_commands.describe(word="要查詢的日文單字")
async def lookup(interaction: discord.Interaction, word: str) -> None:
    bot = interaction.client
    if not isinstance(bot, VocabBot):
        return
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await bot.lookup_word(word))


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


def format_answer_feedback(
    question: QuizQuestion,
    index: int,
    selected: str,
    correct: bool,
    new_label: Label,
) -> str:
    header = f"第 {index + 1} 題"
    question_text = f"題目：{question.prompt}"
    if correct:
        result = f"{header}：答對了。\n{question_text}"
    else:
        selected_meaning = ""
        if question.option_explanations and selected in question.option_explanations:
            selected_meaning = f"\n你選的「{selected}」意思是：{question.option_explanations[selected]}"
        result = (
            f"{header}：答錯了。\n"
            f"{question_text}\n"
            f"你的答案：{selected}{selected_meaning}\n"
            f"正確答案：{question.correct_answer}"
        )
    return (
        f"{result}\n"
        f"{question.explanation}\n"
        f"目前標籤：{LABEL_NAMES[new_label.value]}"
    )


def format_quiz_history(session: QuizSession) -> str:
    return "\n\n".join(session.history or [])


def format_quiz_message(session: QuizSession) -> str:
    parts = []
    history = format_quiz_history(session)
    if history:
        parts.append(history)
    parts.append(format_question(session.current, session.index, len(session.questions)))
    return "\n\n".join(parts)


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
