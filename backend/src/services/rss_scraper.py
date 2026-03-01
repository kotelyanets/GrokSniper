"""
rss_scraper.py
--------------
Fetches real-time crypto news from multiple top-tier RSS feeds.
Tracks processed URLs to prevent duplicate analysis.
"""

import asyncio
import logging
import feedparser
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Global set to prevent duplicate processing within a session
_processed_urls = set()

# Multiple top-tier crypto news sources for maximum coverage
RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cryptoslate.com/feed/",
    "https://bitcoinmagazine.com/.rss/full/",
    "https://decrypt.co/feed",
]


def _source_from_url(feed_url: str) -> str:
    """Derive a readable source name from the feed URL."""
    domain = urlparse(feed_url).netloc.replace("www.", "")
    return domain.split(".")[0] + "_rss"


async def fetch_latest_news() -> dict | None:
    """
    Fetches the latest unprocessed article across all RSS feeds.
    Returns a dict if a new item is found, else None.
    """
    global _processed_urls
    from bs4 import BeautifulSoup

    for feed_url in RSS_FEEDS:
        try:
            # Run blocking parser in thread
            feed = await asyncio.to_thread(feedparser.parse, feed_url)

            if not feed.entries:
                continue

            source = _source_from_url(feed_url)

            # Look for the first entry that hasn't been processed yet
            for entry in feed.entries:
                entry_url = entry.get("link")
                if entry_url and entry_url not in _processed_urls:
                    _processed_urls.add(entry_url)

                    title_raw = entry.get("title", "No Title")
                    summary_raw = entry.get("summary", "No Summary")

                    # Strip HTML tags using BeautifulSoup for robustness
                    title = BeautifulSoup(title_raw, "html.parser").get_text()
                    summary = BeautifulSoup(summary_raw, "html.parser").get_text()

                    # Final regex cleanup for any missed brackets
                    title = re.sub(r'<[^>]+>', '', title)
                    summary = re.sub(r'<[^>]+>', '', summary)

                    # Combine title and summary for the AI analyzer
                    combined_text = f"TITLE: {title}\nSUMMARY: {summary}"

                    logger.info(f"RSS [{source}]: Found new article: {title}")
                    return {
                        "text": combined_text,
                        "url": entry_url,
                        "source": source,
                    }

        except Exception as e:
            logger.error(f"Error fetching RSS from {feed_url}: {e}")
            continue

    return None
