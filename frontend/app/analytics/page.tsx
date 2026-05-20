"use client";

import { useEffect, useState, useCallback } from "react";
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid,
    Tooltip as RechartsTooltip, ResponsiveContainer,
    PieChart, Pie, Cell, BarChart, Bar
} from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const usdFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

function formatUSD(value: number): string {
    return usdFormatter.format(value);
}

interface EquityData {
    date: string;
    cumulative_pnl: number;
    trade_pnl: number;
    ticker: string;
}

interface AnalyticsData {
    total_trades: number;
    win_rate: number;
    total_pnl: number;
    equity_curve: EquityData[];
    error?: string;
}

interface FeatureImportance {
    word: string;
    importance: number;
}

interface MLData {
    status: string;
    message: string;
    metrics?: {
        accuracy_oob: number;
        total_features: number;
        has_micro_features: boolean;
        top_features: FeatureImportance[];
        last_trained_timestamp: number;
    }
}

// ── Reusable metric card ───────────────────────────────────────────────────
function MetricCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
    return (
        <div style={{
            background: "var(--bg-card)", border: "1px solid var(--border)",
            borderRadius: "12px", padding: "20px", position: "relative", overflow: "hidden",
        }}>
            <div style={{
                position: "absolute", top: -20, left: -20, width: "70px", height: "70px",
                background: color ?? "var(--cyan)", borderRadius: "50%", filter: "blur(24px)", opacity: 0.14,
                pointerEvents: "none",
            }} />
            <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", fontWeight: 500, letterSpacing: "0.18em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "10px" }}>
                {label}
            </p>
            <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "28px", fontWeight: 700, color: color ?? "var(--text-primary)", letterSpacing: "-0.02em", lineHeight: 1, margin: "0 0 4px" }}>
                {value}
            </p>
            {sub && <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)", margin: 0 }}>{sub}</p>}
        </div>
    );
}

// ── Custom recharts tooltip ────────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
        <div style={{
            background: "var(--bg-surface)", border: "1px solid var(--border-cyan)",
            borderRadius: "8px", padding: "10px 14px",
            fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-primary)"
        }}>
            <p style={{ color: "var(--text-muted)", marginBottom: "4px" }}>{new Date(label).toLocaleString()}</p>
            <p style={{ color: "var(--cyan)" }}>PnL: <strong>{formatUSD(payload[0].value)}</strong></p>
        </div>
    );
};

// ── Empty state ────────────────────────────────────────────────────────────
function EmptyState() {
    return (
        <div style={{
            background: "var(--bg-card)", border: "1px solid var(--border)",
            borderRadius: "12px", padding: "64px 32px", textAlign: "center"
        }}>
            {/* Crosshair icon */}
            <div style={{ display: "flex", justifyContent: "center", marginBottom: "20px" }}>
                <div style={{
                    width: "56px", height: "56px", borderRadius: "50%",
                    background: "rgba(0,212,255,0.06)", border: "1px solid rgba(0,212,255,0.15)",
                    display: "flex", alignItems: "center", justifyContent: "center"
                }}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--cyan)" strokeWidth="1.5">
                        <circle cx="12" cy="12" r="9" />
                        <circle cx="12" cy="12" r="3" />
                        <line x1="12" y1="3" x2="12" y2="9" />
                        <line x1="12" y1="15" x2="12" y2="21" />
                        <line x1="3" y1="12" x2="9" y2="12" />
                        <line x1="15" y1="12" x2="21" y2="12" />
                    </svg>
                </div>
            </div>
            <p style={{ fontFamily: "var(--font-syne)", fontSize: "16px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "8px" }}>
                No Trade Data Yet
            </p>
            <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "12px", color: "var(--text-muted)", maxWidth: "340px", margin: "0 auto" }}>
                Analytics will populate once the bot executes and closes paper trades. Let the automation loop run.
            </p>
        </div>
    );
}

export default function AnalyticsPage() {
    const [data, setData] = useState<AnalyticsData | null>(null);
    const [mlData, setMlData] = useState<MLData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchAnalytics = useCallback(async () => {
        setError(null);
        setLoading(true);
        try {
            const fetchOpts = {
                cache: 'no-store' as const,
                headers: {
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            };
            const res = await fetch(`${API}/api/analytics?t=${Date.now()}`, fetchOpts);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const json = await res.json();
            if (json.error) throw new Error(json.error);
            setData(json);

            // Fetch ML Data
            const mlRes = await fetch(`${API}/api/ml/status?t=${Date.now()}`, fetchOpts);
            if (mlRes.ok) {
                const mlJson = await mlRes.json();
                setMlData(mlJson);
            }
        } catch (e: unknown) {
            // Show a friendly message — not a hard error block
            setError(e instanceof Error ? e.message : "Cannot reach backend");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchAnalytics(); }, [fetchAnalytics]);

    const pnlPositive = data && data.total_pnl >= 0;
    const strokeColor = pnlPositive ? "var(--green)" : "var(--red)";
    const wins = data ? Math.round((data.win_rate / 100) * data.total_trades) : 0;
    const losses = data ? data.total_trades - wins : 0;
    const pieData = [
        { name: "Wins", value: wins || 1, color: "var(--green)" },
        { name: "Losses", value: losses || 0, color: "var(--red)" },
    ];

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>

            {/* ── Header ───────────────────────────────────────────────────────── */}
            <div className="page-enter" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
                <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
                        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="var(--cyan)" strokeWidth="1.5">
                            <polyline points="1,13 5,7 8,10 12,4 17,8" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        <h1 style={{ fontFamily: "var(--font-syne)", fontSize: "28px", fontWeight: 800, letterSpacing: "-0.03em", color: "var(--text-primary)", margin: 0 }}>
                            Performance Analytics
                        </h1>
                    </div>
                    <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)", margin: 0, letterSpacing: "0.05em" }}>
                        PAPER TRADING · CUMULATIVE PNL & TRADE ACCURACY
                    </p>
                </div>
                <button
                    onClick={fetchAnalytics}
                    disabled={loading}
                    style={{
                        display: "flex", alignItems: "center", gap: "6px",
                        padding: "7px 14px", borderRadius: "8px",
                        background: "var(--bg-card)", border: "1px solid var(--border)",
                        fontFamily: "var(--font-jetbrains)", fontSize: "11px", letterSpacing: "0.08em",
                        color: loading ? "var(--text-muted)" : "var(--text-secondary)",
                        textTransform: "uppercase", cursor: "pointer", opacity: loading ? 0.6 : 1
                    }}
                >
                    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5"
                        style={{ animation: loading ? "spin 1s linear infinite" : "none" }}>
                        <path d="M1 5.5A4.5 4.5 0 1 0 5.5 1" strokeLinecap="round" />
                        <path d="M1 1.5v3.5h3.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {loading ? "SYNCING…" : "REFRESH"}
                </button>
            </div>

            {/* ── Backend offline banner (soft, not blocking) ───────────────────── */}
            {error && (
                <div style={{
                    display: "flex", alignItems: "center", gap: "10px",
                    padding: "10px 14px", borderRadius: "8px",
                    background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.2)",
                    fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--amber)"
                }}>
                    <svg width="13" height="13" viewBox="0 0 13 13" fill="currentColor">
                        <path d="M6.5 1a5.5 5.5 0 1 0 0 11A5.5 5.5 0 0 0 6.5 1zm0 9a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm.5-4h-1V3.5h1V6z" />
                    </svg>
                    Backend unreachable — {error} · Showing last cached data
                </div>
            )}

            {/* ── Loading shimmer ───────────────────────────────────────────────── */}
            {loading && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px" }}>
                    {[...Array(3)].map((_, i) => (
                        <div key={i} className="shimmer" style={{ height: "100px", borderRadius: "12px" }} />
                    ))}
                </div>
            )}

            {/* ── Stats row ────────────────────────────────────────────────────── */}
            {data && !loading && (
                <div className="page-enter page-enter-delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "16px" }}>
                    <MetricCard
                        label="Net PnL"
                        value={data.total_pnl >= 0 ? `+${formatUSD(data.total_pnl)}` : formatUSD(data.total_pnl)}
                        sub="Simulated paper returns"
                        color={pnlPositive ? "var(--green)" : "var(--red)"}
                    />
                    <MetricCard
                        label="Win Rate"
                        value={`${data.win_rate.toFixed(1)}%`}
                        sub={`${wins} wins · ${losses} losses`}
                        color="var(--cyan)"
                    />
                    <MetricCard
                        label="Closed Trades"
                        value={`${data.total_trades}`}
                        sub="Paper executions only"
                        color="var(--violet)"
                    />
                </div>
            )}

            {/* ── Charts ───────────────────────────────────────────────────────── */}
            {data && data.total_trades > 0 ? (
                <div className="page-enter page-enter-delay-2" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "16px" }}>

                    {/* Equity Curve */}
                    <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "12px", padding: "20px" }}>
                        <p style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "16px" }}>
                            Equity Curve
                        </p>
                        <div style={{ height: "300px" }}>
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={data.equity_curve} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                                    <defs>
                                        <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor={pnlPositive ? "#22c55e" : "#ef4444"} stopOpacity={0.25} />
                                            <stop offset="95%" stopColor={pnlPositive ? "#22c55e" : "#ef4444"} stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                    <XAxis
                                        dataKey="date"
                                        tickFormatter={(v) => new Date(v).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                                        stroke="rgba(255,255,255,0.15)"
                                        tick={{ fontFamily: "var(--font-jetbrains)", fontSize: 10, fill: "var(--text-muted)" }}
                                        tickMargin={8}
                                    />
                                    <YAxis
                                        stroke="rgba(255,255,255,0.15)"
                                        tick={{ fontFamily: "var(--font-jetbrains)", fontSize: 10, fill: "var(--text-muted)" }}
                                        tickFormatter={(v) => `$${v}`}
                                    />
                                    <RechartsTooltip content={<ChartTooltip />} />
                                    <Area type="monotone" dataKey="cumulative_pnl" stroke={strokeColor} strokeWidth={2} fill="url(#areaFill)" dot={false} />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* Win/Loss Pie */}
                    <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "12px", padding: "20px", display: "flex", flexDirection: "column" }}>
                        <p style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "16px" }}>
                            Trade Accuracy
                        </p>
                        <div style={{ flex: 1, position: "relative", minHeight: "200px" }}>
                            <ResponsiveContainer width="100%" height="100%">
                                <PieChart>
                                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={75} paddingAngle={4} dataKey="value" stroke="none">
                                        {pieData.map((_, i) => (
                                            <Cell key={i} fill={pieData[i].color} />
                                        ))}
                                    </Pie>
                                    <RechartsTooltip contentStyle={{ background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: "6px", fontSize: "11px", fontFamily: "var(--font-jetbrains)" }} />
                                </PieChart>
                            </ResponsiveContainer>
                            <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", pointerEvents: "none" }}>
                                <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "24px", fontWeight: 700, color: "var(--text-primary)" }}>
                                    {data.win_rate.toFixed(0)}%
                                </span>
                                <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.12em", textTransform: "uppercase" }}>
                                    Win Rate
                                </span>
                            </div>
                        </div>
                        {/* Legend */}
                        <div style={{ display: "flex", justifyContent: "center", gap: "20px", marginTop: "12px" }}>
                            {[{ label: "Wins", count: wins, color: "var(--green)" }, { label: "Losses", count: losses, color: "var(--red)" }].map((l) => (
                                <div key={l.label} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <div style={{ width: "8px", height: "8px", borderRadius: "2px", background: l.color }} />
                                    <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)", letterSpacing: "0.05em" }}>
                                        {l.label} ({l.count})
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Trade PnL Bar Chart */}
                    {data.equity_curve.length > 1 && (
                        <div style={{ gridColumn: "1 / -1", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "12px", padding: "20px" }}>
                            <p style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "16px" }}>
                                Per-Trade PnL
                            </p>
                            <div style={{ height: "200px" }}>
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={data.equity_curve} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                                        <XAxis
                                            dataKey="ticker"
                                            stroke="rgba(255,255,255,0.15)"
                                            tick={{ fontFamily: "var(--font-jetbrains)", fontSize: 10, fill: "var(--text-muted)" }}
                                        />
                                        <YAxis
                                            stroke="rgba(255,255,255,0.15)"
                                            tick={{ fontFamily: "var(--font-jetbrains)", fontSize: 10, fill: "var(--text-muted)" }}
                                            tickFormatter={(v) => `$${v}`}
                                        />
                                        <RechartsTooltip contentStyle={{ background: "var(--bg-surface)", border: "1px solid var(--border)", borderRadius: "6px", fontSize: "11px", fontFamily: "var(--font-jetbrains)" }} />
                                        <Bar dataKey="trade_pnl" radius={[4, 4, 0, 0]}>
                                            {data.equity_curve.map((entry, i) => (
                                                <Cell key={i} fill={entry.trade_pnl >= 0 ? "rgba(34,197,94,0.7)" : "rgba(239,68,68,0.7)"} />
                                            ))}
                                        </Bar>
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    )}

                    {/* ── ML Architecture Panel ── */}
                    {mlData && mlData.status === "trained" && mlData.metrics && (
                        <div style={{ gridColumn: "1 / -1", background: "var(--bg-card)", border: "1px solid rgba(139,92,246,0.3)", borderRadius: "12px", padding: "24px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "20px" }}>
                                <div style={{ width: "36px", height: "36px", borderRadius: "8px", background: "rgba(139,92,246,0.15)", display: "flex", alignItems: "center", justifyContent: "center", border: "1px solid rgba(139,92,246,0.4)" }}>
                                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--violet)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.29 7 12 12 20.71 7"/><line x1="12" y1="22" x2="12" y2="12"/></svg>
                                </div>
                                <div>
                                    <h3 style={{ fontFamily: "var(--font-syne)", fontSize: "16px", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>Machine Learning Engine</h3>
                                    <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--violet)", margin: 0, marginTop: "2px" }}>RandomForestRegressor ∘ TF-IDF Vectors</p>
                                </div>
                            </div>
                            
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "16px", marginBottom: "24px" }}>
                                <div style={{ background: "rgba(0,0,0,0.2)", padding: "16px", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.05)" }}>
                                    <div style={{ fontSize: "10px", color: "var(--text-muted)", fontFamily: "var(--font-jetbrains)", textTransform: "uppercase", marginBottom: "4px" }}>Predictive Accuracy (OOB)</div>
                                    <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--violet)", fontFamily: "var(--font-jetbrains)" }}>{(mlData.metrics.accuracy_oob * 100).toFixed(1)}%</div>
                                </div>
                                <div style={{ background: "rgba(0,0,0,0.2)", padding: "16px", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.05)" }}>
                                    <div style={{ fontSize: "10px", color: "var(--text-muted)", fontFamily: "var(--font-jetbrains)", textTransform: "uppercase", marginBottom: "4px" }}>Total Features</div>
                                    <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-jetbrains)" }}>{mlData.metrics.total_features}</div>
                                </div>
                                <div style={{ background: "rgba(0,0,0,0.2)", padding: "16px", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.05)" }}>
                                    <div style={{ fontSize: "10px", color: "var(--text-muted)", fontFamily: "var(--font-jetbrains)", textTransform: "uppercase", marginBottom: "4px" }}>Micro-Markets</div>
                                    <div style={{ fontSize: "24px", fontWeight: 700, color: mlData.metrics.has_micro_features ? "var(--green)" : "var(--text-muted)", fontFamily: "var(--font-jetbrains)" }}>{mlData.metrics.has_micro_features ? "ACTIVE" : "OFF"}</div>
                                </div>
                            </div>

                            <p style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "16px" }}>
                                Top Influential News Tokens (Feature Importance)
                            </p>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                                {mlData.metrics.top_features.map((feat, idx) => {
                                    // Calculate relative opacity based on rank
                                    const opacity = Math.max(0.15, 1 - (idx * 0.05));
                                    return (
                                        <div key={idx} style={{
                                            background: `rgba(139,92,246,${opacity})`,
                                            border: `1px solid rgba(139,92,246,${opacity + 0.2})`,
                                            padding: "6px 12px",
                                            borderRadius: "100px",
                                            display: "flex",
                                            alignItems: "center",
                                            gap: "8px"
                                        }}>
                                            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "12px", color: "#fff", fontWeight: 500 }}>{feat.word}</span>
                                            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "rgba(255,255,255,0.6)" }}>{(feat.importance * 100).toFixed(2)}%</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                !loading && <EmptyState />
            )}

            <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
    );
}
