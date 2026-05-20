"use client";

import React, { useEffect, useRef } from "react";
import { createChart, ColorType, LineSeries } from "lightweight-charts";

interface TickerResult {
  symbol: string;
  equity_curve: { timestamp: string; equity: number }[];
}

interface StressTestChartProps {
  tickerResults: TickerResult[];
}

const COLOR_MAP: Record<string, string> = {
  "BTC/USDT": "#f59e0b", // Gold
  "ETH/USDT": "#3b82f6", // Blue
  "SOL/USDT": "#a855f7", // Purple
  "DOGE/USDT": "#ea580c", // Orange
  "XRP/USDT": "#06b6d4", // Teal/Cyan
};

export default function StressTestChart({ tickerResults }: StressTestChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartContainerRef.current || !tickerResults || tickerResults.length === 0) return;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#71717a",
      },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.02)" },
        horzLines: { color: "rgba(255, 255, 255, 0.02)" },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: {
        borderVisible: false,
        timeVisible: true,
      },
      rightPriceScale: {
        borderVisible: false,
        borderColor: "rgba(255, 255, 255, 0.06)",
      },
      crosshair: {
        vertLine: { color: "rgba(255, 255, 255, 0.1)", width: 1, style: 3 },
        horzLine: { color: "rgba(255, 255, 255, 0.1)", width: 1, style: 3 },
      },
    });

    tickerResults.forEach((tickerData) => {
      const color = COLOR_MAP[tickerData.symbol] || "#d4d4d8";

      // @ts-ignore
      const series = chart.addSeries(LineSeries, {
        color: color,
        lineWidth: 2,
        title: tickerData.symbol.replace("/USDT", ""),
      });

      // Сортируем по времени и форматируем
      const formattedData = tickerData.equity_curve
        .map((point) => {
          // lightweight-charts требует unix timestamp в секундах или YYYY-MM-DD строку
          const timestampSec = Math.floor(new Date(point.timestamp).getTime() / 1000);
          return {
            time: timestampSec,
            value: point.equity,
          };
        })
        .sort((a, b) => a.time - b.time);

      // Удаление дубликатов по времени
      const uniqueData = [];
      const seen = new Set();
      for (const d of formattedData) {
        if (!seen.has(d.time)) {
          seen.add(d.time);
          uniqueData.push(d);
        }
      }

      series.setData(uniqueData);
    });

    chart.timeScale().fitContent();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [tickerResults]);

  return <div ref={chartContainerRef} style={{ width: "100%", height: "400px" }} />;
}
