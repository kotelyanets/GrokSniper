"use client";

import { useEffect, useState, useCallback } from "react";
import {
    BarChart3,
    ArrowUpRight,
    ArrowDownRight,
    CheckCircle2,
    Clock,
    AlertCircle,
    RefreshCw,
    ChevronDown,
    ChevronRight,
    Brain,
    Loader2,
} from "lucide-react";

const API = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000/ws/dashboard";

interface TradeItem {
    id: string;
    ticker: string;
    action: string;
    amount: number;
    price: number;
    status: string;
    side?: string;
    reason?: string;
    created_at: string;
}

interface Reasoning {
    reasoning: string | null;
    regime: string | null;
    confidence: number | null;
    is_approved?: boolean;
}

function formatPrice(price: number) {
    return price >= 1
        ? `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : `$${price.toFixed(6)}`;
}

function formatTime(iso: string) {
    return new Date(iso).toLocaleString("en-US", {
        month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
        hour12: false,
    });
}

// ---------------------------------------------------------------------------
// Expandable Reasoning Row
// ---------------------------------------------------------------------------
function ReasoningPanel({ tradeId }: { tradeId: string }) {
    const [data, setData] = useState<Reasoning | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        fetch(`${API}/api/trades/${tradeId}/reasoning`)
            .then((r) => r.json())
            .then(setData)
            .catch(() => setData({ reasoning: "Failed to load reasoning.", regime: null, confidence: null }))
            .finally(() => setLoading(false));
    }, [tradeId]);

    return (
        <tr>
            <td colSpan={7} className="p-0">
                <div className="mx-4 mb-3 rounded-xl border border-violet-500/20 bg-violet-950/20 p-4 font-mono text-xs">
                    {loading ? (
                        <div className="flex items-center gap-2 text-violet-400">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Loading AI reasoning…
                        </div>
                    ) : (
                        <>
                            <div className="flex items-center gap-3 mb-3">
                                <Brain className="w-4 h-4 text-violet-400 shrink-0" />
                                <span className="text-violet-300 font-bold text-[10px] uppercase tracking-widest">CIO Decision Log</span>
                                {data?.regime && (
                                    <span className="px-2 py-0.5 rounded-md bg-violet-500/15 border border-violet-500/25 text-violet-300 text-[10px] font-bold uppercase tracking-wider">
                                        {data.regime}
                                    </span>
                                )}
                                {data?.confidence !== null && data?.confidence !== undefined && (
                                    <span className="text-gray-500">Confidence: {data.confidence}%</span>
                                )}
                                {data?.is_approved !== undefined && (
                                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${data.is_approved ? "text-emerald-400 bg-emerald-500/10" : "text-red-400 bg-red-500/10"}`}>
                                        {data.is_approved ? "APPROVED" : "REJECTED"}
                                    </span>
                                )}
                            </div>
                            <p className="text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {data?.reasoning ?? "No reasoning data available."}
                            </p>
                        </>
                    )}
                </div>
            </td>
        </tr>
    );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function TradesPage() {
    const [trades, setTrades] = useState<TradeItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [wsConnected, setWsConnected] = useState(false);
    const [batchSize, setBatchSize] = useState(15);
    const [visibleCount, setVisibleCount] = useState(15);
    const [expandedId, setExpandedId] = useState<string | null>(null);

    const fetchTrades = useCallback(async () => {
        setError(null);
        try {
            const res = await fetch(`${API}/api/trades`);
            if (!res.ok) throw new Error("API error");
            setTrades(await res.json());
        } catch {
            setError("Cannot reach backend — is the server running?");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchTrades();
        const interval = setInterval(fetchTrades, 30_000);
        return () => clearInterval(interval);
    }, [fetchTrades]);

    // WebSocket for real-time trade pushes
    useEffect(() => {
        if (typeof window === "undefined") return;
        let ws: WebSocket;
        let reconnectTimer: ReturnType<typeof setTimeout>;
        let delay = 1000;

        const connect = () => {
            ws = new WebSocket(WS_URL);
            ws.onopen = () => { setWsConnected(true); delay = 1000; };
            ws.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    if (msg.type === "bot_state" && msg.last_action !== "None") {
                        fetchTrades();
                    }
                } catch { }
            };
            ws.onclose = () => {
                setWsConnected(false);
                reconnectTimer = setTimeout(() => { delay = Math.min(delay * 2, 30000); connect(); }, delay);
            };
            ws.onerror = () => ws.close();
        };
        connect();
        return () => { ws?.close(); clearTimeout(reconnectTimer); };
    }, [fetchTrades]);

    const visibleTrades = trades.slice(0, visibleCount);

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-4">
                <div>
                    <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
                        <BarChart3 className="w-6 h-6 text-violet-400" />
                        Trade History
                    </h1>
                    <p className="text-sm text-gray-500 mt-0.5">All executed orders · live from database</p>
                </div>
                <div className="flex items-center gap-3">
                    {/* WS status pill */}
                    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium
            ${wsConnected ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400" : "bg-amber-500/10 border-amber-500/20 text-amber-400"}`}>
                        <span className="relative flex h-1.5 w-1.5">
                            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${wsConnected ? "bg-emerald-400" : "bg-amber-400"}`} />
                            <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${wsConnected ? "bg-emerald-400" : "bg-amber-400"}`} />
                        </span>
                        {wsConnected ? "Live" : "Reconnecting…"}
                    </div>
                    <div className="relative">
                        <select
                            value={batchSize}
                            onChange={(e) => { const s = Number(e.target.value); setBatchSize(s); setVisibleCount(s); }}
                            className="appearance-none bg-white/5 border border-white/10 text-gray-300 rounded-lg pl-3 pr-8 py-1.5 text-xs font-medium focus:outline-none hover:bg-white/10 transition-all cursor-pointer"
                        >
                            <option value={5}>Show 5</option>
                            <option value={10}>Show 10</option>
                            <option value={15}>Show 15</option>
                            <option value={50}>Show 50</option>
                            <option value={100}>Show 100</option>
                        </select>
                        <ChevronDown className="w-3.5 h-3.5 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    </div>
                    <button
                        onClick={fetchTrades}
                        disabled={loading}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/5 border border-white/10 text-gray-300 hover:bg-white/10 hover:text-white transition-all disabled:opacity-50"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* Error */}
            {error && (
                <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-950/40 border border-red-800/50 text-red-400 text-sm">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    {error}
                </div>
            )}

            {/* Stats bar */}
            <div className="grid grid-cols-3 gap-4">
                {[
                    { label: "Total Trades", value: trades.length, color: "text-white" },
                    { label: "BUY Orders", value: trades.filter((t) => t.action === "BUY").length, color: "text-emerald-400" },
                    { label: "SELL Orders", value: trades.filter((t) => t.action === "SELL").length, color: "text-red-400" },
                ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-sm px-5 py-4">
                        <p className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">{label}</p>
                        <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
                    </div>
                ))}
            </div>

            {/* Table — expandable rows */}
            <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden flex flex-col">
                <div className="overflow-x-auto flex-1">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-white/10">
                                <th className="px-4 py-3.5 w-8" />
                                {["ID", "Time", "Ticker", "Type", "Amount", "Price", "Status"].map((col) => (
                                    <th key={col} className="px-4 py-3.5 text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                                        {col}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                            {loading && trades.length === 0 ? (
                                [...Array(Math.min(batchSize, 6))].map((_, i) => (
                                    <tr key={i} className="animate-pulse">
                                        {[...Array(8)].map((_, j) => (
                                            <td key={j} className="px-4 py-4"><div className="h-3 bg-white/5 rounded w-16" /></td>
                                        ))}
                                    </tr>
                                ))
                            ) : visibleTrades.length === 0 ? (
                                <tr>
                                    <td colSpan={8} className="px-6 py-16 text-center text-sm text-gray-600">
                                        No trades yet — trigger the bot from the Dashboard.
                                    </td>
                                </tr>
                            ) : (
                                visibleTrades.flatMap((t) => {
                                    const isExpanded = expandedId === t.id;
                                    return [
                                        <tr
                                            key={t.id}
                                            onClick={() => setExpandedId(isExpanded ? null : t.id)}
                                            className="hover:bg-white/5 transition-colors cursor-pointer group"
                                        >
                                            {/* Expand chevron */}
                                            <td className="px-4 py-3.5 text-gray-600 group-hover:text-gray-400 transition-colors">
                                                {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                                            </td>
                                            <td className="px-4 py-3.5 font-mono text-[11px] text-gray-600 group-hover:text-gray-500">
                                                {t.id.slice(0, 8)}…
                                            </td>
                                            <td className="px-4 py-3.5 text-gray-400 text-xs whitespace-nowrap">{formatTime(t.created_at)}</td>
                                            <td className="px-4 py-3.5 font-bold text-white">{t.ticker}</td>
                                            <td className="px-4 py-3.5">
                                                <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-xs font-bold
                          ${t.action === "BUY"
                                                        ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20"
                                                        : "bg-red-500/15 text-red-400 border border-red-500/20"
                                                    }`}>
                                                    {t.action === "BUY" ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                                                    {t.action}
                                                    {t.side && <span className="ml-1 text-[9px] opacity-70">({t.side})</span>}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3.5 text-gray-300 font-mono tabular-nums">{Number(t.amount).toFixed(4)}</td>
                                            <td className="px-4 py-3.5 text-gray-300 font-mono tabular-nums">{formatPrice(t.price)}</td>
                                            <td className="px-4 py-3.5">
                                                {t.status === "CLOSED" || t.status === "success" || t.status === "SUCCESS" ? (
                                                    <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400">
                                                        <CheckCircle2 className="w-3.5 h-3.5" /> Success
                                                    </span>
                                                ) : t.status === "OPEN" ? (
                                                    <span className="inline-flex items-center gap-1.5 text-xs text-amber-400">
                                                        <Clock className="w-3.5 h-3.5" /> Open
                                                    </span>
                                                ) : (
                                                    <span className="inline-flex items-center gap-1.5 text-xs text-red-400">
                                                        <AlertCircle className="w-3.5 h-3.5" /> Failed
                                                    </span>
                                                )}
                                            </td>
                                        </tr>,
                                        // Expandable reasoning panel
                                        ...(isExpanded ? [<ReasoningPanel key={`reason-${t.id}`} tradeId={t.id} />] : []),
                                    ];
                                })
                            )}
                        </tbody>
                    </table>
                </div>
                {visibleCount < trades.length && (
                    <div className="p-3 border-t border-white/5 flex justify-center bg-transparent">
                        <button
                            onClick={() => setVisibleCount((p) => p + batchSize)}
                            className="px-4 py-1.5 rounded-lg text-xs font-medium bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 transition-all"
                        >
                            Load More ({trades.length - visibleCount} remaining)
                        </button>
                    </div>
                )}
            </div>

            {/* Hint */}
            <p className="text-center text-xs text-gray-600">
                💡 Click any row to expand the <span className="text-violet-400">AI CIO reasoning</span> for that trade.
            </p>
        </div>
    );
}
