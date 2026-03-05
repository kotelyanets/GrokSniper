"use client";

import { useEffect, useState, useCallback } from "react";
import {
    Newspaper,
    ArrowUpRight,
    ArrowDownRight,
    AlertCircle,
    RefreshCw,
    Brain,
    ChevronDown,
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface NewsItem {
    id: string;
    source: string;
    raw_text: string;
    ticker: string | null;
    sentiment_score: number | null;
    confidence: number | null;
    created_at: string;
}

function SentimentBadge({ score }: { score: number | null }) {
    if (score === null) return <span className="text-xs text-gray-600 px-2 py-0.5 rounded border border-gray-800">No score</span>;
    const positive = score >= 0;
    const abs = Math.abs(score);
    const label = abs >= 0.6 ? (positive ? "Strongly Bullish" : "Strongly Bearish")
        : abs >= 0.3 ? (positive ? "Bullish" : "Bearish")
            : "Neutral";
    return (
        <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold
      ${positive
                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/25"
                : score === 0
                    ? "bg-gray-500/15 text-gray-400 border border-gray-600/25"
                    : "bg-red-500/15 text-red-300 border border-red-500/25"
            }`}>
            {positive ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
            {label} ({positive ? "+" : ""}{score.toFixed(3)})
        </span>
    );
}

function formatTime(iso: string) {
    return new Date(iso).toLocaleString("en-US", {
        month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
        hour12: false,
    });
}

export default function AnalysisPage() {
    const [news, setNews] = useState<NewsItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [batchSize, setBatchSize] = useState(15);
    const [visibleCount, setVisibleCount] = useState(15);

    const fetchNews = useCallback(async () => {
        setError(null);
        try {
            const res = await fetch(`${API}/api/news`);
            if (!res.ok) throw new Error("API error");
            setNews(await res.json());
        } catch {
            setError("Cannot reach backend — is the server running?");
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchNews();
        const interval = setInterval(fetchNews, 15_000);
        return () => clearInterval(interval);
    }, [fetchNews]);

    const bullish = news.filter(n => (n.sentiment_score ?? 0) > 0).length;
    const bearish = news.filter(n => (n.sentiment_score ?? 0) < 0).length;

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
                        <Brain className="w-6 h-6 text-cyan-400" />
                        AI Analysis
                    </h1>
                    <p className="text-sm text-gray-500 mt-0.5">Grok sentiment analysis on processed news signals</p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="relative">
                        <select
                            value={batchSize}
                            onChange={(e) => {
                                const size = Number(e.target.value);
                                setBatchSize(size);
                                setVisibleCount(size);
                            }}
                            className="appearance-none bg-gray-800/80 border border-gray-700 text-gray-300 rounded-lg pl-3 pr-8 py-1.5 text-xs font-medium focus:outline-none focus:ring-1 focus:ring-violet-500/50 hover:bg-gray-700 hover:text-white transition-all cursor-pointer"
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
                        onClick={fetchNews}
                        disabled={loading}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-800/80 border border-gray-700 text-gray-300 hover:bg-gray-700 hover:text-white transition-all disabled:opacity-50"
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
                    { label: "Signals Analyzed", value: news.length, color: "text-white" },
                    { label: "Bullish", value: bullish, color: "text-emerald-400" },
                    { label: "Bearish", value: bearish, color: "text-red-400" },
                ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-xl border border-gray-800 bg-gray-900/50 backdrop-blur-sm px-5 py-4">
                        <p className="text-[11px] text-gray-500 uppercase tracking-wider font-semibold">{label}</p>
                        <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
                    </div>
                ))}
            </div>

            {/* News cards */}
            {loading ? (
                <div className="space-y-4">
                    {[...Array(4)].map((_, i) => (
                        <div key={i} className="rounded-2xl border border-gray-800 bg-gray-900/50 p-6 animate-pulse space-y-3">
                            <div className="h-4 bg-gray-800 rounded w-3/4" />
                            <div className="h-3 bg-gray-800 rounded w-full" />
                            <div className="h-3 bg-gray-800 rounded w-1/2" />
                        </div>
                    ))}
                </div>
            ) : news.length === 0 ? (
                <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-16 text-center text-sm text-gray-600">
                    <Newspaper className="w-10 h-10 text-gray-800 mx-auto mb-4" />
                    No signals yet — trigger the bot from the Dashboard.
                </div>
            ) : (
                <div className="space-y-4">
                    {news.slice(0, visibleCount).map((item) => (
                        <div
                            key={item.id}
                            className="rounded-2xl border border-gray-800 bg-gray-900/50 backdrop-blur-sm p-6
                         hover:border-gray-700 transition-all duration-200 space-y-4 group"
                        >
                            {/* Top row */}
                            <div className="flex items-start justify-between gap-4">
                                <div className="flex items-center gap-2.5">
                                    {item.ticker && (
                                        <span className="px-2.5 py-0.5 rounded-md bg-gray-800 border border-gray-700 text-white text-xs font-bold tracking-wider">
                                            {item.ticker}
                                        </span>
                                    )}
                                    <span className="text-[11px] text-gray-600 uppercase tracking-wider font-medium">
                                        via {item.source}
                                    </span>
                                </div>
                                <span className="text-xs text-gray-600 whitespace-nowrap">{formatTime(item.created_at)}</span>
                            </div>

                            {/* News text */}
                            <p className="text-sm text-gray-300 leading-relaxed">{item.raw_text}</p>

                            {/* Sentiment + confidence */}
                            <div className="flex items-center gap-3 flex-wrap pt-1">
                                <SentimentBadge score={item.sentiment_score} />
                                {item.confidence !== null && (
                                    <div className="flex items-center gap-2">
                                        <div className="h-1.5 rounded-full bg-gray-800 w-24 overflow-hidden">
                                            <div
                                                className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-violet-500 transition-all"
                                                style={{ width: `${item.confidence}%` }}
                                            />
                                        </div>
                                        <span className="text-xs text-gray-500">{item.confidence}% confidence</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}

                    {visibleCount < news.length && (
                        <div className="p-3 border-t border-gray-800/50 flex justify-center bg-transparent mt-4">
                            <button
                                onClick={() => setVisibleCount((prev) => prev + batchSize)}
                                className="px-6 py-2 rounded-lg text-sm font-medium bg-gray-800/50 border border-gray-700/50 text-gray-400 hover:text-white hover:bg-gray-700/80 transition-all hover:border-gray-600"
                            >
                                Load More ({news.length - visibleCount} remaining)
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
