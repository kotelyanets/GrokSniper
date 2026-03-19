from unittest.mock import AsyncMock, patch

import pytest

from backend.src.services import telegram_bot


def test_escape_html_escapes_quotes_and_tags():
    raw = "<b>O'Reilly \"Alpha\" & Co</b>"
    escaped = telegram_bot.escape_html(raw)
    assert escaped == "&lt;b&gt;O&#39;Reilly &quot;Alpha&quot; &amp; Co&lt;/b&gt;"


def test_split_telegram_text_respects_limit_and_keeps_content():
    text = "line1\n" + ("x" * 5000)
    chunks = telegram_bot._split_telegram_text(text, max_len=4096)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "".join(chunks) == text


@pytest.mark.asyncio
async def test_send_telegram_message_splits_and_sends_reply_markup_only_first_chunk(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "100")

    post_mock = AsyncMock()
    response_mock = AsyncMock()
    response_mock.raise_for_status = lambda: None
    post_mock.return_value = response_mock

    fake_client = AsyncMock()
    fake_client.post = post_mock
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    long_text = "a" * 5000
    markup = {"inline_keyboard": [[{"text": "Refresh", "callback_data": "refresh"}]]}

    with patch("backend.src.services.telegram_bot.httpx.AsyncClient", return_value=fake_client):
        await telegram_bot.send_telegram_message(long_text, reply_markup=markup)

    assert post_mock.await_count == 2
    first_call_json = post_mock.await_args_list[0].kwargs["json"]
    second_call_json = post_mock.await_args_list[1].kwargs["json"]
    assert "reply_markup" in first_call_json
    assert "reply_markup" not in second_call_json
    assert len(first_call_json["text"]) <= 4096
    assert len(second_call_json["text"]) <= 4096
