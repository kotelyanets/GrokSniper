"use client";

import React, { useEffect, useRef } from "react";
import { createChart, ColorType, Time, AreaSeries } from "lightweight-charts";

interface ChartProps {
  data: { time: number; value: number }[];
  colors?: {
    backgroundColor?: string;
    lineColor?: string;
    textColor?: string;
    areaTopColor?: string;
    areaBottomColor?: string;
  };
}

export default function BacktestChart({ data, colors }: ChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: colors?.backgroundColor || "transparent" },
        textColor: colors?.textColor || "#71717a",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderVisible: false,
      }
    });

    // @ts-ignore - lightweight-charts v5 API
    const newSeries = chart.addSeries(AreaSeries, {
      lineColor: colors?.lineColor || "#10b981",
      topColor: colors?.areaTopColor || "rgba(16, 185, 129, 0.3)",
      bottomColor: colors?.areaBottomColor || "rgba(16, 185, 129, 0.0)",
    });
    
    // De-duplicate times and sort
    const uniqueMap = new Map();
    for (const d of data) {
        uniqueMap.set(d.time, d);
    }
    const finalData = Array.from(uniqueMap.values()).sort((a,b) => a.time - b.time);

    newSeries.setData(finalData as any);
    chart.timeScale().fitContent();

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [data, colors]);

  return <div ref={chartContainerRef} style={{ width: "100%", height: "400px" }} />;
}
