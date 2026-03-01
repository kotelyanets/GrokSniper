"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Clock,
  DollarSign,
  Newspaper,
  TrendingUp,
  Zap,
  RefreshCw,
  AlertCircle,
  ChevronDown,
  X,
  ShoppingCart,
  Bot,
  CheckCircle2,
} from "lucide-react";

// Dynamically import the chart to avoid SSR issues
const LiveChart = dynamic(() => import("@/components/LiveChart"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full flex items-center justify-center text-gray-600 text-sm animate-pulse">
      Loading chart…
    </div>
  ),
});

const API = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000/ws/dashboard";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface NewsItem {
  id: string;
  source: string;
  raw_text: string;
  ticker: string | null;
  sentiment_score: number | null;
  confidence: number | null;
  created_at: string;
}

interface TradeItem {
  id: string;
  ticker: string;
  action: string;
  amount: number;
  price: number;
  status: string;
  is_closed: boolean;
  created_at: string;
}

interface BotState {
  status: string;
  last_action: string;
  started_at: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
function useFlash(value: string | number) {
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const prev = useRef(value);
  useEffect(() => {
    if (prev.current === value) return;
    const up = Number(value) > Number(prev.current);
    setFlash(up ? "up" : "down");
    prev.current = value;
    const t = setTimeout(() => setFlash(null), 800);
    return () => clearTimeout(t);
  }, [value]);
  return flash;
}

function useDashboardWS(onMessage: (msg: Record<string, unknown>) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(1000);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    if (typeof window === "undefined") return;
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectDelay.current = 1000;
    };
    ws.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data));
      } catch { }
    };
    ws.onclose = () => {
      setConnected(false);
      // Exponential backoff reconnect (max 30s)
      setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000);
        connect();
      }, reconnectDelay.current);
    };
    ws.onerror = () => ws.close();
  }, [onMessage]);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return connected;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function StatCard({
  title,
  value,
  sub,
  icon: Icon,
  accentClass,
  pulse = false,
}: {
  title: string;
  value: string;
  sub?: string;
  icon: React.ElementType;
  accentClass: string;
  pulse?: boolean;
}) {
  const flash = useFlash(value);
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border bg-white/5 backdrop-blur-md p-6 flex items-start gap-4 group transition-all duration-300
        ${flash === "up" ? "border-emerald-500/60 bg-emerald-500/5" : flash === "down" ? "border-red-500/60 bg-red-500/5" : "border-white/10 hover:border-white/20"}`}
    >
      {/* Glow blob */}
      <div className={`absolute -top-8 -left-8 w-32 h-32 ${accentClass} rounded-full blur-2xl opacity-20 group-hover:opacity-35 transition-opacity`} />
      <div className="flex-shrink-0 w-11 h-11 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
        <Icon className="w-5 h-5 text-white/70" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] text-gray-500 uppercase tracking-[0.15em] font-semibold mb-1">{title}</p>
        <div className="flex items-center gap-2.5">
          <p className={`text-2xl font-bold tracking-tight transition-colors duration-500 ${flash === "up" ? "text-emerald-400" : flash === "down" ? "text-red-400" : "text-white"}`}>
            {value}
          </p>
          {pulse && (
            <span className="relative flex h-2.5 w-2.5 mt-0.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </span>
          )}
        </div>
        {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function SentimentBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="text-xs text-gray-600">—</span>;
  const positive = score >= 0;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold tabular-nums
      ${positive
        ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/20"
        : "bg-red-500/15 text-red-400 border border-red-500/20"
      }`}
    >
      {positive ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
      {positive ? "+" : ""}{score.toFixed(2)}
    </span>
  );
}

function timeAgo(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function formatPrice(price: number) {
  return price >= 1
    ? `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : `$${price.toFixed(6)}`;
}

// ---------------------------------------------------------------------------
// Manual Trade Modal
// ---------------------------------------------------------------------------
function ManualTradeModal({
  open,
  onClose,
  onRefresh,
}: {
  open: boolean;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [ticker, setTicker] = useState("BTCUSDT");
  const [amount, setAmount] = useState("50");
  const [busy, setBusy] = useState<"BUY" | "SELL" | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const execute = async (action: "BUY" | "SELL") => {
    const num = parseFloat(amount);
    if (isNaN(num) || num < 10) { setToast({ msg: "Minimum $10 USDT", ok: false }); return; }
    setBusy(action);
    try {
      const res = await fetch(`${API}${action === "BUY" ? "/api/buy" : "/api/sell"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: ticker.toUpperCase(), amount_usdt: num }),
      });
      const data = await res.json();
      if (!res.ok || data.status === "error") throw new Error(data.message || "Trade failed");
      setToast({ msg: `${action} order placed! (${data.order?.status || "ok"})`, ok: true });
      onRefresh();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setToast({ msg: `Error: ${msg}`, ok: false });
    } finally {
      setBusy(null);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl border border-white/10 bg-gray-950/95 backdrop-blur-xl p-6 shadow-2xl shadow-black/60 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShoppingCart className="w-5 h-5 text-fuchsia-400" />
            <h2 className="text-sm font-bold text-white uppercase tracking-wide">Manual Execution</h2>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Inputs */}
        <div className="space-y-3">
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-xs font-semibold">TICKER</span>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              className="w-full bg-white/5 border border-white/10 rounded-xl pl-16 pr-4 py-3 text-sm text-white
                         focus:outline-none focus:border-fuchsia-500/50 uppercase font-mono transition-colors"
            />
          </div>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-xs font-semibold">SIZE ($)</span>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              min="10"
              step="1"
              className="w-full bg-white/5 border border-white/10 rounded-xl pl-16 pr-4 py-3 text-sm text-white
                         focus:outline-none focus:border-fuchsia-500/50 font-mono transition-colors"
            />
          </div>
        </div>

        {/* Toast */}
        {toast && (
          <div className={`text-xs px-3 py-2 rounded-lg border ${toast.ok ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400" : "bg-red-500/10 border-red-500/20 text-red-400"}`}>
            {toast.msg}
          </div>
        )}

        {/* Buttons */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={() => execute("BUY")}
            disabled={busy !== null}
            className="flex-1 py-3 rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/30
                       hover:bg-emerald-500/25 hover:border-emerald-500/60 font-bold text-sm transition-all disabled:opacity-40 active:scale-95"
          >
            {busy === "BUY" ? "Executing…" : "⬆ LONG"}
          </button>
          <button
            onClick={() => execute("SELL")}
            disabled={busy !== null}
            className="flex-1 py-3 rounded-xl bg-red-500/15 text-red-300 border border-red-500/30
                       hover:bg-red-500/25 hover:border-red-500/60 font-bold text-sm transition-all disabled:opacity-40 active:scale-95"
          >
            {busy === "SELL" ? "Executing…" : "⬇ SHORT"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function DashboardPage() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [trades, setTrades] = useState<TradeItem[]>([]);
  const [stats, setStats] = useState({
    total_balance: 0,
    pnl_24h: 0,
    total_trades: 0,
    signals_processed: 0,
    holdings: [] as { coin: string; amount: number; value_usdt: number }[],
  });
  const [botState, setBotState] = useState<BotState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [tradeModalOpen, setTradeModalOpen] = useState(false);
  const isFetching = useRef(false);

  // Pagination
  const [batchSizeNews, setBatchSizeNews] = useState(5);
  const [visibleCountNews, setVisibleCountNews] = useState(5);
  const [batchSizePositions, setBatchSizePositions] = useState(5);
  const [visibleCountPositions, setVisibleCountPositions] = useState(5);

  const fetchData = useCallback(async () => {
    if (isFetching.current) return;
    isFetching.current = true;
    setError(null);
    try {
      const [newsRes, tradesRes, statsRes] = await Promise.all([
        fetch(`${API}/api/news`),
        fetch(`${API}/api/trades`),
        fetch(`${API}/api/stats`),
      ]);
      if (!newsRes.ok || !tradesRes.ok || !statsRes.ok) throw new Error("API error");
      const [newsData, tradesData, statsData] = await Promise.all([
        newsRes.json(), tradesRes.json(), statsRes.json(),
      ]);
      setNews(newsData);
      setTrades(tradesData);
      setStats(statsData);
      setLastRefresh(new Date());
    } catch {
      setError("Cannot reach backend — is the server running?");
    } finally {
      setLoading(false);
      isFetching.current = false;
    }
  }, []);

  // WebSocket handler — updates bot state from WS pushes, refreshes data on signals
  const handleWsMessage = useCallback((msg: Record<string, unknown>) => {
    if (msg.type === "bot_state") {
      setBotState(msg as unknown as BotState);
      setError(null);
    }
    // Refresh data if bot just completed an action (new trade/news)
    if (msg.type === "bot_state" && typeof msg.last_action === "string" && msg.last_action !== "None") {
      fetchData();
    }
  }, [fetchData]);

  const wsConnected = useDashboardWS(handleWsMessage);

  // Initial data load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Fallback polling every 30s (for when WS is down)
  useEffect(() => {
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const openPositions = useMemo(() => trades.filter((t) => !t.is_closed && t.action === "BUY"), [trades]);
  const tradeHistory = useMemo(() => trades.filter((t) => t.is_closed || t.action === "SELL"), [trades]);

  // Uptime calc
  const uptime = useMemo(() => {
    if (!botState?.started_at) return "";
    const ms = Date.now() - new Date(botState.started_at).getTime();
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    return `${h}h ${m}m`;
  }, [botState]);

  return (
    <>
      <ManualTradeModal open={tradeModalOpen} onClose={() => setTradeModalOpen(false)} onRefresh={fetchData} />

      <div className="space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Dashboard</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Live overview ·{" "}
              {lastRefresh ? `Updated ${timeAgo(lastRefresh.toISOString())}` : "Connecting…"}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* WS Status */}
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium
              ${wsConnected
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                : "bg-amber-500/10 border-amber-500/20 text-amber-400"
              }`}>
              <span className="relative flex h-1.5 w-1.5">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${wsConnected ? "bg-emerald-400" : "bg-amber-400"}`} />
                <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${wsConnected ? "bg-emerald-400" : "bg-amber-400"}`} />
              </span>
              {wsConnected ? "Live" : "Reconnecting…"}
            </div>

            {/* Refresh */}
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium
                         bg-white/5 border border-white/10 text-gray-300
                         hover:bg-white/10 hover:text-white transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-950/40 border border-red-800/50 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* ── Stats ─────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard
            title="Binance Balance"
            value={`$${stats.total_balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            sub="Available USDT"
            icon={DollarSign}
            accentClass="bg-cyan-400"
          />
          <StatCard
            title="Total PnL"
            value={`${stats.pnl_24h >= 0 ? "+" : ""}$${stats.pnl_24h.toFixed(2)}`}
            sub={`${stats.total_trades} total trades`}
            icon={TrendingUp}
            accentClass={stats.pnl_24h >= 0 ? "bg-emerald-400" : "bg-red-400"}
          />
          <StatCard
            title="Bot Signal Health"
            value={error ? "Offline" : "Active"}
            sub={error ? "Backend unreachable" : `${stats.signals_processed} signals processed`}
            icon={Activity}
            accentClass={error ? "bg-red-400" : "bg-violet-400"}
            pulse={!error}
          />
        </div>

        {/* ── AI Engine Status Bar ──────────────────────────────────────── */}
        {botState && (
          <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-md p-5 flex items-center justify-between gap-6">
            <div className="flex items-center gap-4">
              <div className="relative flex items-center justify-center w-12 h-12 rounded-full bg-blue-500/15 border border-blue-500/30 shrink-0">
                <Bot className="w-5 h-5 text-blue-400" />
              </div>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-sm font-bold text-blue-100 uppercase tracking-wide">AI Engine</h3>
                  <span className="flex h-2 w-2 relative">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
                  </span>
                </div>
                <p className="text-white font-medium">{botState.status}</p>
              </div>
            </div>
            <div className="hidden md:flex flex-col text-right border-l border-white/10 pl-6 shrink-0">
              <p className="text-[11px] text-blue-400/80 uppercase font-semibold tracking-wider mb-1">Last Action</p>
              <p className="text-sm text-gray-300 max-w-xs truncate font-mono" title={botState.last_action}>
                {botState.last_action}
              </p>
              <p className="text-[10px] text-gray-600 mt-1.5 font-mono">UPTIME: {uptime}</p>
            </div>
          </div>
        )}

        {/* ── Holdings ─────────────────────────────────────────────────── */}
        {stats.holdings.length > 0 && (
          <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden p-6">
            <div className="flex items-center gap-2 mb-4">
              <Zap className="w-4 h-4 text-cyan-400" />
              <h2 className="text-sm font-semibold text-white">Current Holdings</h2>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-4">
              {stats.holdings.map((h) => (
                <div key={h.coin} className="p-3 rounded-xl bg-white/5 border border-white/10">
                  <p className="text-[10px] text-gray-500 uppercase font-bold mb-1">{h.coin}</p>
                  <p className="text-sm font-bold text-white">{h.amount.toFixed(4)}</p>
                  <p className="text-[10px] text-gray-500">${h.value_usdt.toFixed(2)}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Live Chart ───────────────────────────────────────────────── */}
        <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/10">
            <div className="flex items-center gap-2">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-cyan-400" />
              </span>
              <span className="text-sm font-semibold text-white">BTCUSDT</span>
              <span className="text-xs text-gray-500 bg-white/5 px-2 py-0.5 rounded font-mono">BINANCE</span>
            </div>
            <span className="text-xs text-gray-500">Live · Real-time</span>
          </div>
          <div className="h-[460px] w-full">
            <LiveChart />
          </div>
        </div>

        {/* ── Bottom Row: News + Positions ─────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Live News Signals */}
          <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
              <div className="flex items-center gap-2">
                <Newspaper className="w-4 h-4 text-cyan-400" />
                <h2 className="text-sm font-semibold text-white">Live News Signals</h2>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500 hidden sm:inline">{news.length} records</span>
                <div className="relative">
                  <select
                    value={batchSizeNews}
                    onChange={(e) => { const s = Number(e.target.value); setBatchSizeNews(s); setVisibleCountNews(s); }}
                    className="appearance-none bg-white/5 border border-white/10 text-gray-300 rounded-lg pl-3 pr-8 py-1 text-xs font-medium focus:outline-none hover:bg-white/10 transition-all cursor-pointer"
                  >
                    <option value={5}>Show 5</option>
                    <option value={10}>Show 10</option>
                    <option value={15}>Show 15</option>
                    <option value={50}>Show 50</option>
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>
            </div>
            {loading ? (
              <div className="flex flex-col divide-y divide-white/5">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="flex items-start gap-4 px-6 py-4 animate-pulse">
                    <div className="w-10 h-10 rounded-lg bg-white/5 flex-shrink-0" />
                    <div className="flex-1 space-y-2">
                      <div className="h-3 bg-white/5 rounded w-3/4" />
                      <div className="h-3 bg-white/5 rounded w-1/2" />
                    </div>
                  </div>
                ))}
              </div>
            ) : news.length === 0 ? (
              <div className="px-6 py-12 text-center text-sm text-gray-600">
                No news signals yet — click <strong className="text-gray-400">Test Bot</strong> to trigger.
              </div>
            ) : (
              <>
                <ul className="divide-y divide-white/5 flex-1">
                  {news.slice(0, visibleCountNews).map((s) => (
                    <li key={s.id} className="flex items-start gap-4 px-6 py-4 hover:bg-white/5 transition-colors">
                      <span className="flex-shrink-0 mt-0.5 w-10 h-10 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-[11px] font-bold text-white tracking-wider">
                        {s.ticker ?? "?"}
                      </span>
                      <div className="flex-1 min-w-0 space-y-1.5">
                        <p className="text-sm text-gray-300 leading-snug line-clamp-2">{s.raw_text}</p>
                        <div className="flex items-center gap-2">
                          <SentimentBadge score={s.sentiment_score} />
                          {s.confidence !== null && <span className="text-xs text-gray-600">{s.confidence}% conf.</span>}
                          <span className="text-xs text-gray-600 ml-auto">{timeAgo(s.created_at)}</span>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
                {visibleCountNews < news.length && (
                  <div className="p-3 border-t border-white/5 flex justify-center">
                    <button
                      onClick={() => setVisibleCountNews((p) => p + batchSizeNews)}
                      className="px-4 py-1.5 rounded-lg text-xs font-medium bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 transition-all"
                    >
                      Load More ({news.length - visibleCountNews} remaining)
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Open Positions */}
          <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-emerald-400" />
                <h2 className="text-sm font-semibold text-white">Open Positions</h2>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-500 hidden sm:inline">{openPositions.length} active</span>
                <div className="relative">
                  <select
                    value={batchSizePositions}
                    onChange={(e) => { const s = Number(e.target.value); setBatchSizePositions(s); setVisibleCountPositions(s); }}
                    className="appearance-none bg-white/5 border border-white/10 text-gray-300 rounded-lg pl-3 pr-8 py-1 text-xs font-medium focus:outline-none hover:bg-white/10 transition-all cursor-pointer"
                  >
                    <option value={5}>Show 5</option>
                    <option value={10}>Show 10</option>
                    <option value={15}>Show 15</option>
                    <option value={50}>Show 50</option>
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5">
                    {["Ticker", "Entry Price", "Amount", "Status"].map((col) => (
                      <th key={col} className="px-6 py-3 text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {openPositions.slice(0, visibleCountPositions).map((t) => (
                    <tr key={t.id} className="hover:bg-white/5 transition-colors">
                      <td className="px-6 py-3.5 font-bold text-white">{t.ticker}</td>
                      <td className="px-6 py-3.5 text-gray-300 font-mono tabular-nums">{formatPrice(t.price)}</td>
                      <td className="px-6 py-3.5 text-gray-300 font-mono tabular-nums">{Number(t.amount).toFixed(4)}</td>
                      <td className="px-6 py-3.5">
                        <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400">
                          <span className="relative flex h-1.5 w-1.5">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                          </span>
                          Holding
                        </span>
                      </td>
                    </tr>
                  ))}
                  {openPositions.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-6 py-8 text-center text-sm text-gray-600">No open positions.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {visibleCountPositions < openPositions.length && (
              <div className="p-3 border-t border-white/5 flex justify-center">
                <button onClick={() => setVisibleCountPositions((p) => p + batchSizePositions)}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 transition-all">
                  Load More ({openPositions.length - visibleCountPositions} remaining)
                </button>
              </div>
            )}
          </div>

          {/* Trade History */}
          <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden lg:col-span-2">
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-violet-400" />
                <h2 className="text-sm font-semibold text-white">Trade History</h2>
              </div>
              <span className="text-xs text-gray-500">{tradeHistory.length} records</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/5">
                    {["Ticker", "Action", "Amount", "Price", "Time", "Status"].map((col) => (
                      <th key={col} className="px-6 py-3 text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {tradeHistory.map((t) => (
                    <tr key={t.id} className="hover:bg-white/5 transition-colors">
                      <td className="px-6 py-3.5 font-bold text-white">{t.ticker}</td>
                      <td className="px-6 py-3.5">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold
                          ${t.action.toUpperCase() === "BUY" ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"}`}>
                          {t.action.toUpperCase() === "BUY" ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                          {t.action}
                        </span>
                      </td>
                      <td className="px-6 py-3.5 text-gray-300 font-mono tabular-nums">{Number(t.amount).toFixed(4)}</td>
                      <td className="px-6 py-3.5 text-gray-300 font-mono tabular-nums">{formatPrice(t.price)}</td>
                      <td className="px-6 py-3.5 text-gray-500 text-xs">{timeAgo(t.created_at)}</td>
                      <td className="px-6 py-3.5">
                        <span className="inline-flex items-center gap-1.5 text-xs text-emerald-400">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                          Closed
                        </span>
                      </td>
                    </tr>
                  ))}
                  {tradeHistory.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-6 py-8 text-center text-sm text-gray-600">No trade history yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {/* ── Floating Action Button — Manual Trade ─────────────────────── */}
      <button
        onClick={() => setTradeModalOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-5 py-3 rounded-full
                   bg-gradient-to-r from-fuchsia-600 to-violet-600 text-white font-bold text-sm
                   shadow-xl shadow-fuchsia-900/40 hover:from-fuchsia-500 hover:to-violet-500
                   active:scale-95 transition-all duration-200"
        title="Open Manual Trade"
      >
        <ShoppingCart className="w-4 h-4" />
        Trade
      </button>
    </>
  );
}
