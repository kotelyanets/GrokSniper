"use client";

import { useEffect, useRef, useState, memo } from "react";
import { createChart, ColorType, IChartApi, ISeriesApi, SeriesMarker, Time, CandlestickSeries } from "lightweight-charts";
export interface TradeItem {
    id: string;
    ticker: string;
    action: string;
    amount: number;
    price: number;
    status: string;
    is_closed: boolean;
    created_at: string;
    updated_at?: string;
    pnl_usdt?: number;
}

interface LiveChartProps {
    trades: TradeItem[];
}

const LiveChart = memo(function LiveChart({ trades }: LiveChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const [symbol, setSymbol] = useState("BTCUSDT");

    useEffect(() => {
        if (!chartContainerRef.current) return;

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current) {
                chartRef.current.applyOptions({
                    width: chartContainerRef.current.clientWidth,
                    height: chartContainerRef.current.clientHeight,
                });
            }
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#71717a",
            },
            grid: {
                vertLines: { color: "rgba(255, 255, 255, 0.04)" },
                horzLines: { color: "rgba(255, 255, 255, 0.04)" },
            },
            rightPriceScale: {
                borderColor: "rgba(255, 255, 255, 0.06)",
            },
            timeScale: {
                borderColor: "rgba(255, 255, 255, 0.06)",
                timeVisible: true,
                secondsVisible: false,
            },
            crosshair: {
                vertLine: {
                    color: "#52525b",
                    width: 1,
                    style: 3,
                    labelBackgroundColor: "#27272a",
                },
                horzLine: {
                    color: "#52525b",
                    width: 1,
                    style: 3,
                    labelBackgroundColor: "#27272a",
                },
            },
        });
        
        chartRef.current = chart;

        // @ts-ignore
        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: "#10b981",
            downColor: "#f43f5e",
            borderVisible: false,
            wickUpColor: "#10b981",
            wickDownColor: "#f43f5e",
        });
        
        seriesRef.current = candlestickSeries;

        window.addEventListener("resize", handleResize);
        handleResize(); // Initial sizing

        return () => {
            window.removeEventListener("resize", handleResize);
            chart.remove();
            chartRef.current = null;
            seriesRef.current = null;
        };
    }, []);

    // Fetch data and update chart
    useEffect(() => {
        let isMounted = true;
        
        const fetchData = async () => {
            try {
                // Fetch public Binance klines
                const res = await fetch(`https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=1h&limit=500`);
                if (!res.ok) return;
                const data = await res.json();
                
                if (!isMounted || !seriesRef.current) return;

                const formattedData = data.map((d: any) => ({
                    time: (d[0] / 1000) as Time, // Unix timestamp in seconds
                    open: parseFloat(d[1]),
                    high: parseFloat(d[2]),
                    low: parseFloat(d[3]),
                    close: parseFloat(d[4]),
                }));

                seriesRef.current.setData(formattedData);

                // Add markers based on passed trades
                const markers: SeriesMarker<Time>[] = [];
                
                // Filter trades for this symbol
                const symbolTrades = trades.filter(t => t.ticker === symbol.replace("USDT", ""));

                symbolTrades.forEach(trade => {
                    // Find the exact trade time or map to the nearest candle time
                    const tradeTime = Math.floor(new Date(trade.created_at).getTime() / 1000) as Time;
                    
                    if (trade.action === "LONG") {
                        markers.push({
                            time: tradeTime,
                            position: "belowBar",
                            color: "#10b981",
                            shape: "arrowUp",
                            text: `LONG @ $${trade.price.toFixed(2)}`,
                            size: 2
                        });
                    } else if (trade.action === "SHORT") {
                        markers.push({
                            time: tradeTime,
                            position: "aboveBar",
                            color: "#f43f5e",
                            shape: "arrowDown",
                            text: `SHORT @ $${trade.price.toFixed(2)}`,
                            size: 2
                        });
                    }
                    
                    if (trade.status === "CLOSED" && trade.updated_at) {
                        markers.push({
                            time: Math.floor(new Date(trade.updated_at).getTime() / 1000) as Time,
                            position: trade.action === "LONG" ? "aboveBar" : "belowBar",
                            color: trade.pnl_usdt && trade.pnl_usdt > 0 ? "#10b981" : "#f59e0b",
                            shape: "circle",
                            text: `EXIT ${trade.pnl_usdt && trade.pnl_usdt > 0 ? "+" : ""}$${trade.pnl_usdt?.toFixed(2)}`,
                            size: 1
                        });
                    }
                });

                // Sort markers by time as required by lightweight-charts
                markers.sort((a, b) => (a.time as number) - (b.time as number));
                
                if (markers.length > 0) {
                    // @ts-ignore
                    seriesRef.current.setMarkers(markers);
                }

            } catch (error) {
                console.error("Failed to fetch chart data:", error);
            }
        };

        fetchData();
        
        // Refresh interval every 1 min
        const interval = setInterval(fetchData, 60000);

        return () => {
            isMounted = false;
            clearInterval(interval);
        };
    }, [symbol, trades]);

    return (
        <div style={{ position: "relative", width: "100%", height: "100%" }}>
            {/* Symbol Selector over the chart */}
            <div style={{ position: "absolute", top: "10px", left: "10px", zIndex: 10, display: "flex", gap: "8px" }}>
                {["BTCUSDT", "ETHUSDT", "SOLUSDT"].map(sym => (
                    <button
                        key={sym}
                        onClick={() => setSymbol(sym)}
                        style={{
                            padding: "4px 8px",
                            background: symbol === sym ? "rgba(255, 255, 255, 0.08)" : "rgba(24, 24, 27, 0.5)",
                            border: `1px solid ${symbol === sym ? "rgba(255, 255, 255, 0.15)" : "rgba(255, 255, 255, 0.06)"}`,
                            color: symbol === sym ? "#fafafa" : "#52525b",
                            borderRadius: "4px",
                            fontFamily: "var(--font-jetbrains)",
                            fontSize: "11px",
                            cursor: "pointer",
                            transition: "all 0.15s ease"
                        }}
                    >
                        {sym.replace("USDT", "")}
                    </button>
                ))}
            </div>
            
            <div ref={chartContainerRef} style={{ width: "100%", height: "100%" }} />
        </div>
    );
});

export default LiveChart;
