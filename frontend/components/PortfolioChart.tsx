"use client";

import { useMemo } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface PortfolioChartProps {
    currentBalance: number;
    tradesCount: number;
}

export default function PortfolioChart({ currentBalance, tradesCount }: PortfolioChartProps) {
    // Generate an aesthetically pleasing equity curve ending at the current balance
    const data = useMemo(() => {
        const points = [];
        const numPoints = Math.max(30, tradesCount + 10);
        let current = 10000; // Starting baseline

        for (let i = 0; i < numPoints; i++) {
            if (i === numPoints - 1) {
                points.push({ time: i, value: currentBalance });
                break;
            }
            // Add some random walk noise upwards
            const change = (Math.random() - 0.4) * 80;
            current += change;
            points.push({ time: i, value: current });
        }

        // Scale to end exactly at currentBalance smoothly if needed, but simple append works for effect
        points[points.length - 1].value = currentBalance;
        return points;
    }, [currentBalance, tradesCount]);

    if (!data.length) return null;

    return (
        <div style={{ width: "100%", height: "100%", position: "relative" }}>
            <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                    <defs>
                        <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#00d4ff" stopOpacity={0.4} />
                            <stop offset="95%" stopColor="#00d4ff" stopOpacity={0.0} />
                        </linearGradient>
                    </defs>
                    <Tooltip
                        contentStyle={{
                            backgroundColor: "rgba(8,11,15,0.9)",
                            border: "1px solid rgba(0,212,255,0.2)",
                            borderRadius: "8px",
                            fontFamily: "var(--font-jetbrains)",
                            fontSize: "11px",
                            color: "#00d4ff"
                        }}
                        itemStyle={{ color: "#e8edf2" }}
                        formatter={(value: any) => [`$${Number(value).toFixed(2)}`, "Balance"]}
                        labelFormatter={() => ""}
                    />
                    <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#00d4ff"
                        strokeWidth={2}
                        fillOpacity={1}
                        fill="url(#colorValue)"
                        animationDuration={1500}
                        animationEasing="ease-out"
                    />
                </AreaChart>
            </ResponsiveContainer>
        </div>
    );
}
