"""
telegram_assistant.py
---------------------
Phase 55 — Telegram AI Assistant with voice support and project tooling.

This module provides:
1. Groq Whisper speech-to-text transcription for voice messages.
2. An LLM-powered conversational assistant with project manipulation tools.
3. Per-user chat memory so the AI remembers context within a session.
"""

import os
import io
import logging
import tempfile
from pathlib import Path

import httpx
from groq import Groq, AsyncGroq

from crewai import LLM
from dotenv import load_dotenv

from backend.src.agents.project_tools import (
    read_file,
    list_directory,
    write_file,
    run_command,
    PROJECT_ROOT,
)
from backend.src.agents.trading_tools import (
    get_account_summary,
    close_all_positions,
    request_on_demand_analysis
)

# ---------------------------------------------------------------------------
# Env loading (mirrors board_of_directors.py pattern)
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[3]
_BACKEND_DIR = _HERE.parents[2]

load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv()

logger = logging.getLogger(__name__)

# Claude model env deleted since we transitioned to free Groq.

# ---------------------------------------------------------------------------
# Groq client for Whisper transcription and LLM (chat)
# ---------------------------------------------------------------------------
_groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
groq_client = Groq(api_key=_groq_api_key) if _groq_api_key else None
if not _groq_api_key:
    logger.warning("GROQ_API_KEY not set — AI assistant will use fallback/fail.")

# ---------------------------------------------------------------------------
# Chat memory — simple per-user message history (kept in RAM)
# ---------------------------------------------------------------------------
_chat_histories: dict[int, list[dict]] = {}
MAX_HISTORY = 20  # Keep last 20 messages per user to stay within context limits

SYSTEM_PROMPT = """Ты — GrokSniper AI, элитный ИИ-помощник для криптотрейдинга.
Ты управляешь торговой системой GrokSniper. Твои возможности:

🔧 ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
1. READ_FILE — Чтение файла проекта. Пример: [READ_FILE: path/to/file]
2. LIST_DIR — Список файлов в папке. Пример: [LIST_DIR: .]
3. WRITE_FILE — Запись/редактирование файла.
4. RUN_CMD — Выполнение команды в терминале.
5. GET_ACCOUNT — Узнать текущий баланс и открытые сделки. Пример: [GET_ACCOUNT]
6. ANALYZE — Запросить глубокий анализ Board of Directors для конкретной монеты. Пример: [ANALYZE: BTC]
7. PANIC — Экстренно закрыть ВСЕ сделки и остановить бота. Пример: [PANIC]

📏 ПРАВИЛА:
- Всегда отвечай на РУССКОМ языке.
- Думай пошагово. Если тебя просят проанализировать монету, используй [ANALYZE: TICKER].
- Будь кратким, профессиональным и проактивным.
- Для глубокого анализа графиков всегда вызывай команду ANALYZE.
- Если тебя просят закрыть всё — используй PANIC.
- Корень проекта: """ + str(PROJECT_ROOT) + """

Ты общаешься с владельцем проекта в Telegram. Будь лучшим трейдинг-партнером."""


def _get_history(user_id: int) -> list[dict]:
    """Get or create chat history for a user."""
    if user_id not in _chat_histories:
        _chat_histories[user_id] = []
    return _chat_histories[user_id]


def _trim_history(user_id: int):
    """Keep only the last MAX_HISTORY messages."""
    history = _chat_histories.get(user_id, [])
    if len(history) > MAX_HISTORY:
        _chat_histories[user_id] = history[-MAX_HISTORY:]


# ---------------------------------------------------------------------------
# Voice → Text (Groq Whisper)
# ---------------------------------------------------------------------------
async def transcribe_voice(voice_file_bytes: bytes) -> str:
    """
    Transcribe voice message bytes using Groq's Whisper API.
    Returns the transcribed text.
    """
    if not groq_client:
        return "❌ Groq API key not configured. Cannot transcribe voice."

    try:
        # Write to a temp file because the Groq SDK expects a file-like object
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(voice_file_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=("voice.ogg", audio_file),
                model="whisper-large-v3",
                response_format="text",
            )

        # Clean up temp file
        os.unlink(tmp_path)

        text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
        logger.info(f"Voice transcribed: {text[:100]}...")
        return text

    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return f"❌ Voice transcription failed: {e}"


# ---------------------------------------------------------------------------
# Tool Execution Engine
# ---------------------------------------------------------------------------
def _execute_tools(response_text: str) -> str | None:
    """
    Parse tool calls from the LLM response and execute them.
    Returns the combined tool output, or None if no tools were called.
    """
    import re

    tool_outputs = []

    # READ_FILE
    for match in re.finditer(r"\[READ_FILE:\s*(.+?)\]", response_text):
        path = match.group(1).strip()
        logger.info(f"Tool call: READ_FILE({path})")
        result = read_file(path)
        tool_outputs.append(f"📄 READ_FILE({path}):\n{result}")

    # LIST_DIR
    for match in re.finditer(r"\[LIST_DIR:\s*(.+?)\]", response_text):
        path = match.group(1).strip()
        logger.info(f"Tool call: LIST_DIR({path})")
        result = list_directory(path)
        tool_outputs.append(f"{result}")

    # WRITE_FILE
    for match in re.finditer(
        r"\[WRITE_FILE:\s*(.+?)\]\s*\[CONTENT_START\](.*?)\[CONTENT_END\]",
        response_text,
        re.DOTALL,
    ):
        path = match.group(1).strip()
        content = match.group(2).strip()
        logger.info(f"Tool call: WRITE_FILE({path})")
        result = write_file(path, content)
        tool_outputs.append(f"✏️ WRITE_FILE({path}):\n{result}")

    # RUN_CMD
    for match in re.finditer(r"\[RUN_CMD:\s*(.+?)\]", response_text):
        cmd = match.group(1).strip()
        logger.info(f"Tool call: RUN_CMD({cmd})")
        result = run_command(cmd)
        tool_outputs.append(f"💻 RUN_CMD({cmd}):\n{result}")

    # GET_ACCOUNT
    if "[GET_ACCOUNT]" in response_text:
        logger.info("Tool call: GET_ACCOUNT")
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(get_account_summary()) if not loop.is_running() else "⚠️ Cannot run nested async. Use /status instead."
        tool_outputs.append(f"💰 Account Summary:\n{result}")

    # ANALYZE: TICKER
    for match in re.finditer(r"\[ANALYZE:\s*(\w+?)\]", response_text):
        ticker = match.group(1).strip().upper()
        logger.info(f"Tool call: ANALYZE({ticker})")
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(request_on_demand_analysis(ticker)) if not loop.is_running() else "⚠️ Cannot run nested async. Use /board instead."
        tool_outputs.append(f"🏛️ Analysis for {ticker}:\n{result}")

    # PANIC
    if "[PANIC]" in response_text:
        logger.info("Tool call: PANIC")
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(close_all_positions()) if not loop.is_running() else "⚠️ Cannot run nested async. Use /panic instead."
        tool_outputs.append(f"🚨 Panic Result:\n{result}")

    return "\n\n".join(tool_outputs) if tool_outputs else None


# ---------------------------------------------------------------------------
# Main Chat Function
# ---------------------------------------------------------------------------
async def chat(user_id: int, user_message: str) -> str:
    """
    Process a user message through the AI assistant (Groq llama-3.3-70b-versatile).
    """
    if not _groq_api_key:
        return "❌ Groq API key not configured. Cannot process messages."

    history = _get_history(user_id)
    history.append({"role": "user", "content": user_message})
    _trim_history(user_id)

    client = AsyncGroq(api_key=_groq_api_key)

    try:
        # First LLM call — may contain tool invocations
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
            max_tokens=2048,
            temperature=0,
        )

        assistant_text = response.choices[0].message.content
        logger.info(f"Groq response (first pass): {assistant_text[:200]}...")

        # Check for tools
        tool_output = _execute_tools(assistant_text)

        if tool_output:
            history.append({"role": "assistant", "content": assistant_text})
            # Feed back
            history.append({
                "role": "user", 
                "content": f"РЕЗУЛЬТАТЫ ИНСТРУМЕНТОВ:\n\n{tool_output}\n\nТеперь ответь пользователю на русском языке, основываясь на данных."
            })
            _trim_history(user_id)
            
            final_res = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
                max_tokens=2048,
                temperature=0,
            )
            final_text = final_res.choices[0].message.content
            history.append({"role": "assistant", "content": final_text})
            return final_text
        else:
            history.append({"role": "assistant", "content": assistant_text})
            return assistant_text

    except Exception as e:
        logger.error(f"Chat error for user {user_id}: {e}")
        return f"🚨 AI error: {e}"
