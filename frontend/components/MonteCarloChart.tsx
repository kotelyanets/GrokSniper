"use client";

import React, { useEffect, useRef } from "react";
import { createChart, ColorType, LineSeries } from "lightweight-charts";

interface MonteCarloChartProps {
  curves: number[][]; // 200 curves, each has trades_per_sim + 1 points
  initialBalance: number;
}

export default function MonteCarloChart({ curves, initialBalance }: MonteCarloChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartContainerRef.current || !curves || curves.length === 0) return;

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

    // 1. Отрисовка всех путей (spaghetti curves)
    // Группируем по прибыльности для окрашивания
    curves.forEach((curve) => {
      const finalVal = curve[curve.length - 1];
      const isProfitable = finalVal > initialBalance;
      
      const color = isProfitable 
        ? "rgba(16, 185, 129, 0.08)" // Полупрозрачный зеленый
        : "rgba(244, 63, 94, 0.08)"; // Полупрозрачный красный

      // Добавляем линию
      // @ts-ignore
      const series = chart.addSeries(LineSeries, {
        color: color,
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
      });

      const formattedData = curve.map((val, idx) => ({
        time: idx,
        value: val,
      }));

      series.setData(formattedData);
    });

    // 2. Рассчитаем и добавим медианную кривую (жирная белая линия)
    if (curves.length > 0) {
      const len = curves[0].length;
      const medianCurve = [];
      for (let step = 0; step < len; step++) {
        const stepValues = curves.map((c) => c[step]).sort((a, b) => a - b);
        const mid = Math.floor(stepValues.length / 2);
        const medianVal = stepValues.length % 2 !== 0 
          ? stepValues[mid] 
          : (stepValues[mid - 1] + stepValues[mid]) / 2;
        medianCurve.push(medianVal);
      }

      // @ts-ignore
      const medianSeries = chart.addSeries(LineSeries, {
        color: "rgba(250, 250, 250, 0.85)",
        lineWidth: 3,
        title: "Median",
        priceLineVisible: false,
      });

      const medianData = medianCurve.map((val, idx) => ({
        time: idx,
        value: val,
      }));

      medianSeries.setData(medianData);
    }

    chart.timeScale().fitContent();
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [curves, initialBalance]);

  return <div ref={chartContainerRef} style={{ width: "100%", height: "400px" }} />;
}
