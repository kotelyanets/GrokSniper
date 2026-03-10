"""
test_rss_scraper.py
-------------------
Unit tests for backend/src/services/rss_scraper.py.

All network calls are mocked — feedparser.parse is patched via asyncio.to_thread.
Run with:  pytest backend/tests/test_rss_scraper.py -v
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.src.services import rss_scraper
from backend.src.services.rss_scraper import _source_from_url, fetch_latest_news


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feed(entries):
    """Construct a fake feedparser result object."""
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(url="https://example.com/article/1", title="Bitcoin Surges 10%",
                summary="<p>BTC hit 100k today</p>"):
    entry = MagicMock()
    entry.get = lambda key, default="": {
        "link": url,
        "title": title,
        "summary": summary,
    }.get(key, default)
    return entry


# ---------------------------------------------------------------------------
# _source_from_url — pure function
# ---------------------------------------------------------------------------

class TestSourceFromUrl:
    def test_cointelegraph(self):
        assert _source_from_url("https://cointelegraph.com/rss") == "cointelegraph_rss"

    def test_coindesk(self):
        assert _source_from_url("https://www.coindesk.com/arc/outboundfeeds/rss/") == "coindesk_rss"

    def test_decrypt(self):
        assert _source_from_url("https://decrypt.co/feed") == "decrypt_rss"

    def test_strips_www(self):
        src = _source_from_url("https://www.somesite.io/feed")
        assert "www" not in src

    def test_returns_string(self):
        result = _source_from_url("https://bitcoinmagazine.com/.rss/full/")
        assert isinstance(result, str)
        assert result.endswith("_rss")


# ---------------------------------------------------------------------------
# fetch_latest_news — async, mock feedparser
# ---------------------------------------------------------------------------

class TestFetchLatestNews:

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        """Happy path: fresh article → returns a dict with text, url, source."""
        entry = _make_entry()
        feed = _make_feed([entry])

        # Clear processed URLs state between tests
        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=AsyncMock(return_value=feed)):
            result = await fetch_latest_news()

        assert result is not None
        assert "text" in result
        assert "url" in result
        assert "source" in result

    @pytest.mark.asyncio
    async def test_text_contains_title_and_summary(self):
        entry = _make_entry(title="ETH 2.0 Launch", summary="Ethereum upgrade.")
        feed = _make_feed([entry])
        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=AsyncMock(return_value=feed)):
            result = await fetch_latest_news()

        assert "TITLE:" in result["text"]
        assert "SUMMARY:" in result["text"]

    @pytest.mark.asyncio
    async def test_deduplication_returns_none_second_call(self):
        """Same URL returned twice → second call returns None."""
        entry = _make_entry(url="https://example.com/unique-article-xyz")
        feed = _make_feed([entry])

        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=AsyncMock(return_value=feed)):
            first = await fetch_latest_news()
            # All feeds now see the same processed URL
            second = await fetch_latest_news()

        assert first is not None
        assert second is None

    @pytest.mark.asyncio
    async def test_empty_feeds_return_none(self):
        """All feeds return empty entries → result is None."""
        feed = _make_feed([])
        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=AsyncMock(return_value=feed)):
            result = await fetch_latest_news()

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_in_one_feed_continues_to_next(self):
        """If one feed raises, the scraper tries the remaining feeds."""
        good_entry = _make_entry(url="https://example.com/good-story-abc123")
        good_feed = _make_feed([good_entry])

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("timeout")
            return good_feed

        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=side_effect):
            result = await fetch_latest_news()

        assert result is not None
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_html_stripped_from_title(self):
        """HTML tags in the title are stripped."""
        entry = _make_entry(title="<b>Market pumps</b> 🚀", summary="normal text")
        feed = _make_feed([entry])
        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=AsyncMock(return_value=feed)):
            result = await fetch_latest_news()

        assert "<b>" not in result["text"]
        assert "</b>" not in result["text"]

    @pytest.mark.asyncio
    async def test_url_stored_in_result(self):
        """The URL from the entry appears in the result."""
        url = "https://cointelegraph.com/unique-test-url-888"
        entry = _make_entry(url=url)
        feed = _make_feed([entry])
        rss_scraper._processed_urls.clear()

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=AsyncMock(return_value=feed)):
            result = await fetch_latest_news()

        assert result["url"] == url

    @pytest.mark.asyncio
    async def test_all_feeds_raise_returns_none(self):
        """If every feed errors, the function returns None gracefully."""
        rss_scraper._processed_urls.clear()

        async def always_raise(*args, **kwargs):
            raise RuntimeError("boom")

        with patch("backend.src.services.rss_scraper.asyncio.to_thread",
                   new=always_raise):
            result = await fetch_latest_news()

        assert result is None
