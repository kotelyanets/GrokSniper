"""
test_telegram_bot_alerts.py
============================
Unit tests for the Telegram Notification Service and institutional HTML templates.
Covers escaping, mock HTTP requests, photo alerts, and entry/exit signal templates.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open, ANY
from backend.src.services.telegram_bot import (
    escape_html,
    send_telegram_message,
    send_photo_alert,
    send_entry_alert,
    send_exit_alert
)

class TestTelegramHelpers:
    """Tests utility helpers inside the telegram bot module."""

    def test_escape_html_handles_special_chars(self):
        """escape_html escapes HTML markup characters correctly."""
        assert escape_html("BTC & ETH") == "BTC &amp; ETH"
        assert escape_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
        assert escape_html("") == ""
        assert escape_html(None) == ""


class TestTelegramMessageSending:
    """Tests direct message dispatch logic to configured Telegram channels."""

    @pytest.mark.asyncio
    async def test_skips_when_credentials_missing(self):
        """If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are missing, send skip message."""
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            with patch("httpx.AsyncClient.post") as mock_post:
                await send_telegram_message("Test message")
                mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_to_multiple_recipients(self):
        """Sends message to all configured comma-separated chat IDs."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "TELEGRAM_CHAT_ID": "111111, 222222 ,333333"
        }
        with patch.dict(os.environ, env_vars):
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
                await send_telegram_message("Hello Premium Traders", reply_markup={"inline_keyboard": []})
                
                assert mock_post.call_count == 3
                # Inspect payload of the first request
                kwargs = mock_post.call_args_list[0][1]
                assert kwargs["json"]["chat_id"] == "111111"
                assert kwargs["json"]["text"] == "Hello Premium Traders"
                assert kwargs["json"]["parse_mode"] == "HTML"
                assert kwargs["json"]["reply_markup"] == {"inline_keyboard": []}

    @pytest.mark.asyncio
    async def test_handles_httpx_exception_gracefully(self):
        """If an HTTP error happens, logger records the failure without raising an exception."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "TELEGRAM_CHAT_ID": "999999"
        }
        with patch.dict(os.environ, env_vars):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("Connection refused")):
                # Should not raise exception
                await send_telegram_message("Test failure")


class TestTelegramPhotoAlerts:
    """Tests image/chart reporting via Telegram photo commands."""

    @pytest.mark.asyncio
    async def test_sends_photo_via_python_telegram_bot_library(self):
        """send_photo_alert uses python-telegram-bot library under the hood."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
            "TELEGRAM_CHAT_ID": "55555"
        }
        with patch.dict(os.environ, env_vars):
            mock_bot = MagicMock()
            mock_bot.send_photo = AsyncMock()
            
            with patch("telegram.Bot", return_value=mock_bot), \
                 patch("builtins.open", mock_open(read_data=b"image_data")):
                
                await send_photo_alert("/tmp/chart.png", "Bullish Chart")
                
                mock_bot.send_photo.assert_called_once_with(
                    chat_id="55555",
                    photo=ANY,
                    caption="Bullish Chart",
                    parse_mode="HTML"
                )


class TestInstitutionalHTMLTemplates:
    """Validates the premium Russian localized alert formats."""

    @pytest.mark.asyncio
    async def test_send_entry_alert_crew_ai(self):
        """Correctly templates standard CrewAI entry alert."""
        with patch("backend.src.services.telegram_bot.send_telegram_message", new_callable=AsyncMock) as mock_send:
            await send_entry_alert(
                ticker="SOL",
                action="BUY",
                price=145.2345,
                size=250.0,
                stop_loss=139.50,
                confidence=85,
                ai_reasoning="Breakout above $144 with high volume & positive MACD",
                is_ml_hype=False
            )
            
            mock_send.assert_called_once()
            message_text = mock_send.call_args[0][0]
            
            assert "СИГНАЛ: ОТКРЫТИЕ ПОЗИЦИИ" in message_text
            assert "#SOL" in message_text
            assert "🟢 LONG" in message_text
            assert "ИИ-Совет (CrewAI)" in message_text
            assert "85%" in message_text
            assert "145.2345 USDT" in message_text
            assert "$250.00" in message_text
            assert "139.5000 USDT" in message_text
            assert "tradingview.com" in message_text

    @pytest.mark.asyncio
    async def test_send_entry_alert_ml_hype(self):
        """Correctly templates ML Hype (Local ML Model) entry alert."""
        with patch("backend.src.services.telegram_bot.send_telegram_message", new_callable=AsyncMock) as mock_send:
            await send_entry_alert(
                ticker="BTC",
                action="SELL",
                price=67000.0,
                size=500.0,
                stop_loss=69000.0,
                confidence=92.5,
                ai_reasoning="FUD levels extremely high, RSI overbought divergence",
                is_ml_hype=True
            )
            
            mock_send.assert_called_once()
            message_text = mock_send.call_args[0][0]
            
            assert "🔴 SHORT" in message_text
            assert "ИИ-Модель (ML Hype)" in message_text
            assert "92.5%" in message_text
            assert "67,000.0000 USDT" in message_text

    @pytest.mark.asyncio
    async def test_send_exit_alert_profit(self):
        """Correctly templates profitable exit notification."""
        with patch("backend.src.services.telegram_bot.send_telegram_message", new_callable=AsyncMock) as mock_send:
            await send_exit_alert(
                ticker="ETH",
                exit_label="Trailing Stop Triggered",
                entry_price=3000.0,
                exit_price=3150.0,
                pnl_usd=45.0,
                pnl_pct=5.0,
                side="LONG",
                reference_price=3200.0
            )
            
            mock_send.assert_called_once()
            message_text = mock_send.call_args[0][0]
            
            assert "💰" in message_text
            assert "ЗАКРЫТИЕ ПОЗИЦИИ (LONG)" in message_text
            assert "Trailing Stop Triggered" in message_text
            assert "3,150.0000 USDT" in message_text
            assert "3,000.0000 USDT" in message_text
            assert "Пик (Peak)" in message_text
            assert "3,200.0000 USDT" in message_text
            assert "+5.00%" in message_text
            assert "$+45.00" in message_text

    @pytest.mark.asyncio
    async def test_send_exit_alert_loss(self):
        """Correctly templates loss exit notification with trough details."""
        with patch("backend.src.services.telegram_bot.send_telegram_message", new_callable=AsyncMock) as mock_send:
            await send_exit_alert(
                ticker="ETH",
                exit_label="Hard Stop Loss Hit",
                entry_price=3000.0,
                exit_price=2910.0,
                pnl_usd=-27.0,
                pnl_pct=-3.0,
                side="SHORT",
                reference_price=2890.0
            )
            
            mock_send.assert_called_once()
            message_text = mock_send.call_args[0][0]
            
            assert "📉" in message_text
            assert "ЗАКРЫТИЕ ПОЗИЦИИ (SHORT)" in message_text
            assert "Hard Stop Loss Hit" in message_text
            assert "Мин. (Trough)" in message_text
            assert "-3.00%" in message_text
            assert "$-27.00" in message_text
