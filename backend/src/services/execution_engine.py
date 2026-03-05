"""
execution_engine.py
--------------------
Phase 50.3 — Smart Execution Engine: Sniper Limit Orders.

Strategy:
  1. Fetch the top-of-book bid/ask.
  2. Place a LIMIT order at the best available price (maker fee = 0%).
  3. Poll for fill every 3 seconds for up to `fallback_seconds`.
  4. If still open when the timer expires → cancel and fire a MARKET fallback
     for the remaining unfilled quantity so we never miss the trade entirely.

Return schema
─────────────
{
    "status":      "success" | "failed",
    "exec_style":  "SNIPER_LIMIT" | "FALLBACK_TO_MARKET" | "DRY_RUN",
    "price":       float,          # average fill price
    "amount":      float,          # filled quantity
    "fills":       [],             # raw CCXT fill list (may be empty on testnet)
    "ticker":      str,
    "side":        str,
    "error":       str | None,
}
"""

import asyncio
import logging
import os
import time

import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("groksniper.execution")

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET", "True").lower() == "true"
DRY_RUN            = os.getenv("DRY_RUN", "False").lower() == "true"

# How often to poll order status while waiting for fill (seconds)
_POLL_INTERVAL = 3

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_exchange() -> ccxt.Exchange:
    """Create a fresh authenticated Binance CCXT async client."""
    ex = ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_API_SECRET,
        "enableRateLimit": True,
    })
    if BINANCE_TESTNET:
        ex.set_sandbox_mode(True)
    return ex


def _spot_symbol(ticker: str) -> str:
    """Normalise ticker → 'BTC/USDT'."""
    return f"{ticker}/USDT" if "/" not in ticker else ticker


def _has_keys() -> bool:
    return bool(BINANCE_API_KEY and BINANCE_API_SECRET)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def execute_sniper_order(
    ticker: str,
    side: str,                  # 'buy' | 'sell'
    amount: float,
    fallback_seconds: int = 15,
) -> dict:
    """
    Sniper Limit Order with Market Fallback.

    Parameters
    ----------
    ticker           : base coin e.g. 'BTC' or full symbol 'BTC/USDT'
    side             : 'buy' or 'sell'
    amount           : quantity in base currency (e.g. 0.001 BTC)
    fallback_seconds : seconds to wait before cancelling and using market order

    Returns
    -------
    Result dict — see module docstring for schema.
    """
    side    = side.lower()
    symbol  = _spot_symbol(ticker)

    # ── Dry-run path (no API keys or explicit DRY_RUN) ──────────────────────
    if DRY_RUN or not _has_keys():
        mock_price = 50_000.0
        logger.info(f"[SNIPER DRY-RUN] {side.upper()} {symbol} qty={amount:.6f} @ {mock_price}")
        return {
            "status":     "success",
            "exec_style": "DRY_RUN",
            "price":      mock_price,
            "amount":     amount,
            "fills":      [],
            "ticker":     ticker,
            "side":       side,
            "error":      None,
        }

    exchange = _make_exchange()

    try:
        # ── 1. Fetch order book (top 5 levels) ─────────────────────────────
        order_book = await exchange.fetch_order_book(symbol, limit=5)
        bids = order_book.get("bids", [])   # [[price, qty], ...]
        asks = order_book.get("asks", [])

        if not bids or not asks:
            raise ValueError(f"Empty order book for {symbol}")

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        # ── 2. Determine sniper price ───────────────────────────────────────
        # BUY  → bid at best_bid (passive, maker).  Jump queue: best_bid + 1 tick.
        # SELL → ask at best_ask (passive, maker).  Jump queue: best_ask - 1 tick.
        tick = await _get_tick_size(exchange, symbol)

        if side == "buy":
            limit_price = round(best_bid + tick, 8)   # one tick above best bid
        else:
            limit_price = round(best_ask - tick, 8)   # one tick below best ask

        logger.info(
            f"[SNIPER] {symbol} {side.upper()} | Bid={best_bid} Ask={best_ask} "
            f"tick={tick} → LimitPrice={limit_price} qty={amount:.6f}"
        )

        # ── 3. Place the limit order ────────────────────────────────────────
        if side == "buy":
            order = await exchange.create_limit_buy_order(symbol, amount, limit_price)
        else:
            order = await exchange.create_limit_sell_order(symbol, amount, limit_price)

        order_id  = order["id"]
        exec_style = "SNIPER_LIMIT"
        logger.info(f"[SNIPER] Limit order placed: id={order_id} @ {limit_price}")

        # ── 4. Monitor loop ─────────────────────────────────────────────────
        deadline = time.monotonic() + fallback_seconds
        final_order = order

        while time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            try:
                final_order = await exchange.fetch_order(order_id, symbol)
            except Exception as poll_err:
                logger.warning(f"[SNIPER] Poll error (will retry): {poll_err}")
                continue

            status = final_order.get("status", "open")
            filled = float(final_order.get("filled") or 0)
            logger.info(
                f"[SNIPER] Poll → order {order_id} status={status} "
                f"filled={filled:.6f}/{amount:.6f}"
            )

            if status == "closed":
                # Fully filled — done!
                logger.info(f"[SNIPER] Order {order_id} fully filled as LIMIT.")
                break

        else:
            # ── 5. Fallback: timer expired ──────────────────────────────────
            logger.warning(
                f"[SNIPER] Timer expired after {fallback_seconds}s. "
                f"Cancelling limit order {order_id} and falling back to MARKET."
            )
            try:
                await exchange.cancel_order(order_id, symbol)
            except Exception as cancel_err:
                logger.warning(f"[SNIPER] Cancel failed (may already be filled): {cancel_err}")

            # Re-fetch to get exact filled amount before cancellation
            try:
                final_order = await exchange.fetch_order(order_id, symbol)
            except Exception:
                pass

            already_filled = float(final_order.get("filled") or 0)
            remaining      = round(amount - already_filled, 8)

            if remaining > 0:
                logger.info(
                    f"[SNIPER FALLBACK] Placing MARKET {side.upper()} for remaining "
                    f"{remaining:.6f} {symbol}"
                )
                market_order = await exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=remaining,
                )
                # Merge fill data
                market_filled = float(market_order.get("filled") or remaining)
                market_price  = float(
                    market_order.get("average")
                    or market_order.get("price")
                    or limit_price
                )

                # Compute blended average fill price
                total_filled = already_filled + market_filled
                if total_filled > 0:
                    blended_price = (
                        (already_filled * limit_price + market_filled * market_price)
                        / total_filled
                    )
                else:
                    blended_price = market_price

                exec_style = "FALLBACK_TO_MARKET"
                final_order = {
                    **final_order,
                    "filled":  total_filled,
                    "average": blended_price,
                    "status":  "closed",
                }

        # ── Build result ────────────────────────────────────────────────────
        avg_price  = float(final_order.get("average") or final_order.get("price") or limit_price)
        filled_qty = float(final_order.get("filled") or 0)

        logger.info(
            f"[SNIPER] Done. exec_style={exec_style} filled={filled_qty:.6f} "
            f"avg_price={avg_price:.4f}"
        )

        return {
            "status":     "success",
            "exec_style": exec_style,
            "price":      avg_price,
            "amount":     filled_qty,
            "fills":      final_order.get("trades") or [],
            "ticker":     ticker,
            "side":       side,
            "error":      None,
        }

    except Exception as e:
        logger.error(f"[SNIPER] Critical failure for {symbol} {side}: {e}", exc_info=True)
        return {
            "status":     "failed",
            "exec_style": "FAILED",
            "price":      0.0,
            "amount":     0.0,
            "fills":      [],
            "ticker":     ticker,
            "side":       side,
            "error":      str(e),
        }
    finally:
        await exchange.close()


async def _get_tick_size(exchange: ccxt.Exchange, symbol: str) -> float:
    """
    Fetch the minimum price increment (tick size) for a symbol from market metadata.
    Falls back to a sensible default if unavailable.
    """
    try:
        await exchange.load_markets()
        market = exchange.market(symbol)
        # CCXT nests precision inside 'precision' or 'limits'
        price_precision = market.get("precision", {}).get("price")
        if price_precision:
            # precision can be a number of decimal places (int) or an absolute tick (float)
            if isinstance(price_precision, int):
                return 10 ** (-price_precision)
            return float(price_precision)
    except Exception as e:
        logger.debug(f"[SNIPER] Could not load tick size for {symbol}: {e}")
    return 0.01   # safe fallback for most USDT pairs


# ---------------------------------------------------------------------------
# Telegram execution tag builder
# ---------------------------------------------------------------------------

def build_exec_tag(result: dict) -> str:
    """
    Returns a compact string to embed in Telegram trade alerts.

    Examples:
        '[Execution: SNIPER LIMIT]'
        '[Execution: FALLBACK TO MARKET]'
        '[Execution: DRY RUN]'
    """
    style_map = {
        "SNIPER_LIMIT":       "[Execution: SNIPER LIMIT]",
        "FALLBACK_TO_MARKET": "[Execution: FALLBACK TO MARKET]",
        "DRY_RUN":            "[Execution: DRY RUN]",
        "FAILED":             "[Execution: FAILED]",
    }
    style = result.get("exec_style", "SNIPER_LIMIT")
    return style_map.get(style, f"[Execution: {style}]")
