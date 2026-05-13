# Vocabulary Helper

本機跑的 JLPT N3 單字複習 Discord bot。它會把單字分成：

- `known`：會的
- `reading_unknown`：看過但讀音不記得
- `meaning_unknown`：看過但意思不記得
- `no_memory`：完全沒印象

每天早上自動出 10 題，題型包含意思題、讀音題、已會單字回收，以及 N3 附近的新詞探索。

標籤會依答題狀況自動調整：同一張卡連續答對 3 次才會升成 `known`；已會單字如果在讀音題答錯，會降成 `reading_unknown`，如果在意思題答錯，會降成 `meaning_unknown`。

## 需求

- Python 3.11+
- Discord bot token
- 可選：Ollama + `qwen3:4b` 或 `qwen3:1.7b`

## 安裝

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

編輯 `.env`：

- `DISCORD_TOKEN`：你的 bot token
- `DISCORD_USER_ID`：你的 Discord user id
- `DISCORD_CHANNEL_ID`：每日題目要發送的 channel id；留空時會私訊 `DISCORD_USER_ID`
- `DISCORD_GUILD_ID`：測試用伺服器 id；填了以後 slash command 會更快同步到該伺服器
- `QUIZ_TIME`：每日出題時間，例如 `08:00`
- `OLLAMA_MODEL`：建議先用 `qwen2.5:3b`；翻譯與例句品質比小模型穩
- `OLLAMA_TIMEOUT`：等待本機模型回覆的秒數，預設 `120`
- `MESSAGE_CONTENT_INTENT`：預設 `false`；若要讓 bot 理解一般聊天訊息，需到 Discord Developer Portal 開啟 Message Content Intent 後改成 `true`
- `DICTIONARY_ENABLED`：預設 `true`；先查本地中文覆蓋詞典，查不到才使用 Jisho 字典 API 與 Ollama 翻譯

## 啟動

```powershell
python -m n3_discord_vocab.bot
```

第一次啟動會自動建立 SQLite 資料庫，並放入一小批 N3 程度種子單字。

## Discord 指令

```text
/add word:承る
/add word:承る label:reading_unknown
/mark word:承る label:known
/quiz
/stats
/words
```

私訊裡如果 `/words` 還沒出現，可以直接用文字指令：

```text
!quiz
!stats
!words
!words 10
!add やがて
```

也可以直接跟 bot 說：

```text
把「締め切り」加入，我意思不記得
承る 這個我看過但讀音忘了
add やがて
やがて 是什麼意思？
```

查字典時，bot 會先用本地日中詞典覆蓋表回傳中文；查不到中文時才查 Jisho 英文釋義並交給 Ollama 翻譯。回覆會附一個短句範例；意思題會以短句填空形式出題。

如果 `LLM_ENABLED=true` 且 Ollama 正在跑，bot 會嘗試解析自然語言；失敗時會提示你改用 `/add`。

## 測試

```powershell
pip install -e .[dev]
pytest
```

## 設計筆記

模型只負責「理解你想做什麼」和「補題目文字」，真正的記憶狀態、排程、答題紀錄都寫在 SQLite。這樣模型就算偶爾恍神，也不會污染你的學習歷史。
