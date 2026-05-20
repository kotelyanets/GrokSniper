"use client";

import { useMemo } from "react";
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";

interface WinRateChartProps {
    totalTrades: number;
    winRate: number; // 0 to 100
}

export default function WinRateChart({ totalTrades, winRate }: WinRateChartProps) {
    const data = useMemo(() => {
        if (totalTrades === 0) {
            return [
                { name: "Profit", value: 0, color: "#10b981" },
                { name: "Loss", value: 0, color: "#f43f5e" },
            ];
        }
        const wins_pct = winRate / 100;
        const wins = Math.floor(totalTrades * wins_pct);
        const losses = totalTrades - wins;

        return [
            { name: "Profit", value: wins, color: "#10b981" },
            { name: "Loss", value: losses, color: "#f43f5e" },
        ];
    }, [totalTrades]);

    return (
        <div style={{ width: "100%", height: "100%", position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                    <Tooltip
                        contentStyle={{
                            backgroundColor: "rgba(9, 9, 11, 0.95)",
                            border: "1px solid rgba(255, 255, 255, 0.08)",
                            borderRadius: "8px",
                            fontFamily: "var(--font-jetbrains)",
                            fontSize: "11px",
                            color: "#d4d4d8"
                        }}
                        itemStyle={{ color: "#fafafa" }}
                    />
                    <Pie
                        data={data}
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={65}
                        stroke="none"
                        paddingAngle={5}
                        dataKey="value"
                        animationDuration={1500}
                    >
                        {data.map((entry, index) => (
                            <Cell
                                key={`cell-${index}`}
                                fill={entry.color}
                            />
                        ))}
                    </Pie>
                </PieChart>
            </ResponsiveContainer>

            {/* Center label */}
            <div style={{
                position: "absolute",
                top: "50%", left: "50%",
                transform: "translate(-50%, -50%)",
                textAlign: "center",
                display: "flex", flexDirection: "column",
                alignItems: "center", justifyContent: "center"
            }}>
                <span style={{
                    fontFamily: "var(--font-jetbrains)",
                    fontSize: "20px", fontWeight: 800,
                    color: "var(--text-primary)",
                    lineHeight: 1
                }}>
                    {data[0].value + data[1].value > 0 ? Math.round((data[0].value / (data[0].value + data[1].value)) * 100) : 0}%
                </span>
                <span style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "8px", color: "var(--text-muted)",
                    letterSpacing: "0.1em", textTransform: "uppercase",
                    marginTop: "2px"
                }}>
                    WIN RATE
                </span>
            </div>
        </div>
    );
}
