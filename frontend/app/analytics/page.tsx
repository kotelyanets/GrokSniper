"use client";

import { useEffect, useState, useCallback } from "react";
import {
    AreaChart,
    Area,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip as RechartsTooltip,
    ResponsiveContainer,
    PieChart,
    Pie,
    Cell,
    BarChart,
    Bar
} from "recharts";
import { Activity, Target, TrendingUp, AlertCircle, RefreshCw } from "lucide-react";

const API = "http://127.0.0.1:8000";

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

function StatCard({
    title,
    value,
    sub,
    icon: Icon,
    trendColor,
}: {
    title: string;
    value: string;
    sub: string;
    icon: React.ElementType;
    trendColor: string;
}) {
    return (
        <div className={`relative overflow-hidden rounded-2xl border bg-white/5 backdrop-blur-md p-6 flex items-start gap-4 hover:border-white/20 transition-all border-white/10`}>
            <div className={`absolute -top-8 -left-8 w-32 h-32 ${trendColor} rounded-full blur-2xl opacity-10`} />
            <div className="flex-shrink-0 w-11 h-11 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
                <Icon className={`w-5 h-5 ${trendColor.replace("bg-", "text-")}`} />
            </div>
            <div className="flex-1 min-w-0">
                <p className="text-[10px] text-gray-400 uppercase tracking-[0.15em] font-semibold mb-1">{title}</p>
                <p className={`text-2xl font-bold tracking-tight text-white`}>{value}</p>
                <p className="text-xs text-gray-500 mt-1">{sub}</p>
            </div>
        </div>
    );
}

export default function AnalyticsPage() {
    const [data, setData] = useState<AnalyticsData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchAnalytics = useCallback(async () => {
        setError(null);
        try {
            const res = await fetch(`${API}/api/analytics`);
            if (!res.ok) throw new Error("API error");
            const json = await res.json();
            if (json.error) throw new Error(json.error);
            setData(json);
        } catch (e: any) {
            setError(e.message || "Cannot reach backend");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAnalytics();
    }, [fetchAnalytics]);

    const pnlColor = data && data.total_pnl >= 0 ? "bg-emerald-400" : "bg-red-400";
    const strokeColor = data && data.total_pnl >= 0 ? "#34d399" : "#f87171"; // Emerald-400 or Red-400
    const fillColor = data && data.total_pnl >= 0 ? "url(#colorGreen)" : "url(#colorRed)";

    // Format data for Recharts Pie
    const wins = data ? Math.round((data.win_rate / 100) * data.total_trades) : 0;
    const losses = data ? data.total_trades - wins : 0;
    const pieData = [
        { name: "Wins", value: wins, color: "#34d399" },
        { name: "Losses", value: losses, color: "#f87171" },
    ];

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
                        <Activity className="w-6 h-6 text-fuchsia-400" />
                        Performance Analytics
                    </h1>
                    <p className="text-sm text-gray-500 mt-0.5">Advanced metrics & equity growth (Paper Trading)</p>
                </div>
                <button
                    onClick={fetchAnalytics}
                    disabled={loading}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 border border-white/10 text-gray-300 hover:bg-white/10 hover:text-white transition-all disabled:opacity-50"
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                    Refresh
                </button>
            </div>

            {error && (
                <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-950/40 border border-red-800/50 text-red-400 text-sm">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    {error}
                </div>
            )}

            {/* Top Stats */}
            {data && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <StatCard
                        title="Total Net PnL"
                        value={`${data.total_pnl >= 0 ? "+" : ""}$${data.total_pnl.toFixed(2)}`}
                        sub="Simulated Returns"
                        icon={TrendingUp}
                        trendColor={pnlColor}
                    />
                    <StatCard
                        title="Win Rate"
                        value={`${data.win_rate.toFixed(1)}%`}
                        sub={`${wins} Win / ${losses} Loss`}
                        icon={Target}
                        trendColor="bg-cyan-400"
                    />
                    <StatCard
                        title="Total Executions"
                        value={`${data.total_trades}`}
                        sub="Closed trades only"
                        icon={Activity}
                        trendColor="bg-violet-400"
                    />
                </div>
            )}

            {/* Charts */}
            {data && data.total_trades > 0 ? (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Equity Curve */}
                    <div className="lg:col-span-2 rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm p-6 flex flex-col">
                        <h2 className="text-sm font-semibold text-white mb-6 flex items-center gap-2">
                            <TrendingUp className="w-4 h-4 text-emerald-400" />
                            Equity Curve
                        </h2>
                        <div className="h-[300px] w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={data.equity_curve} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                    <defs>
                                        <linearGradient id="colorGreen" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#34d399" stopOpacity={0.3} />
                                            <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
                                        </linearGradient>
                                        <linearGradient id="colorRed" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#f87171" stopOpacity={0.3} />
                                            <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" vertical={false} />
                                    <XAxis
                                        dataKey="date"
                                        tickFormatter={(val) => new Date(val).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                        stroke="#ffffff40"
                                        fontSize={11}
                                        tickMargin={10}
                                    />
                                    <YAxis stroke="#ffffff40" fontSize={11} tickFormatter={(val) => `$${val}`} />
                                    <RechartsTooltip
                                        contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px', fontSize: '12px', color: '#fff' }}
                                        itemStyle={{ color: '#fff' }}
                                        labelFormatter={(val) => new Date(val).toLocaleString()}
                                        formatter={(val: number) => [`$${val.toFixed(2)}`, 'Cumulative PnL']}
                                    />
                                    <Area type="monotone" dataKey="cumulative_pnl" stroke={strokeColor} strokeWidth={2} fillOpacity={1} fill={fillColor} />
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* Win/Loss Split */}
                    <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm p-6 flex flex-col justify-between">
                        <h2 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
                            <Target className="w-4 h-4 text-cyan-400" />
                            Trade Accuracy
                        </h2>
                        <div className="flex-1 flex flex-col items-center justify-center relative min-h-[200px]">
                            <ResponsiveContainer width="100%" height="100%">
                                <PieChart>
                                    <Pie
                                        data={pieData}
                                        cx="50%"
                                        cy="50%"
                                        innerRadius={60}
                                        outerRadius={80}
                                        paddingAngle={5}
                                        dataKey="value"
                                        stroke="none"
                                    >
                                        {pieData.map((entry, index) => (
                                            <Cell key={`cell-${index}`} fill={entry.color} />
                                        ))}
                                    </Pie>
                                    <RechartsTooltip
                                        contentStyle={{ backgroundColor: '#111827', borderColor: '#374151', borderRadius: '8px', fontSize: '12px', color: '#fff' }}
                                        itemStyle={{ color: '#fff' }}
                                    />
                                </PieChart>
                            </ResponsiveContainer>
                            {/* Center Text */}
                            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                                <span className="text-2xl font-bold text-white">{data.win_rate.toFixed(0)}%</span>
                                <span className="text-[10px] text-gray-500 uppercase font-semibold tracking-wider">Win Rate</span>
                            </div>
                        </div>
                        <div className="flex justify-center gap-6 mt-4">
                            <div className="flex items-center gap-2">
                                <div className="w-3 h-3 rounded-sm bg-emerald-400"></div>
                                <span className="text-xs text-gray-400 uppercase font-semibold">Wins ({wins})</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <div className="w-3 h-3 rounded-sm bg-red-400"></div>
                                <span className="text-xs text-gray-400 uppercase font-semibold">Losses ({losses})</span>
                            </div>
                        </div>
                    </div>
                </div>
            ) : (
                !loading && !error && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm p-16 text-center text-sm text-gray-500">
                        No closed paper trades available to generate analytics. Let the bot run and execute some trades first!
                    </div>
                )
            )}
        </div>
    );
}
