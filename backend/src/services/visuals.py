import os
import pandas as pd
import mplfinance as mpf
import logging

logger = logging.getLogger(__name__)

def generate_trade_chart(ticker: str, candles_df: pd.DataFrame, action: str, entry_price: float, sl_price: float) -> str:
    """
    Generates a dark-themed candlestick chart using mplfinance and saves to a temp file.
    candles_df should be a pandas DataFrame with at least O, H, L, C, V columns.
    """
    try:
        df = candles_df.copy()

        # Ensure timestamp index for mplfinance
        if "ts" in df.columns:
            # Check if ts is already datetime
            if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
                df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            df.set_index("ts", inplace=True)
        
        # Rename columns to what mplfinance expects
        df.rename(columns={"O": "Open", "H": "High", "L": "Low", "C": "Close", "V": "Volume"}, inplace=True)

        # We only take the last 40 candles to ensure a clean chart
        df = df.tail(40)

        filename = os.path.abspath(f"trade_chart_temp_{ticker.replace('/', '_')}.png")

        # Market direction marker at entry_price
        entry_markers = [float("nan")] * len(df)
        entry_markers[-1] = entry_price

        marker_style = '^' if action.upper() == "LONG" else 'v'
        marker_color = 'lime' if action.upper() == "LONG" else 'red'

        apds = [
            mpf.make_addplot(entry_markers, type='scatter', markersize=200, marker=marker_style, color=marker_color)
        ]

        # Horizontal Line for SL
        hlines = dict(hlines=[sl_price], colors=['r'], linestyle='--', linewidths=1.5)

        # Styling
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', gridstyle=':')

        mpf.plot(
            df, 
            type='candle', 
            style=s, 
            volume=True, 
            addplot=apds, 
            hlines=hlines,
            savefig=filename, 
            title=f"{ticker} - {action} (AI Setup)", 
            tight_layout=True
        )

        return filename
    except Exception as e:
        logger.error(f"Failed to generate trade chart: {e}")
        return ""
