"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import {
  TrendingUp, TrendingDown, Activity, DollarSign,
  Zap, Shield, Send
} from "lucide-react";

// Dynamically import charts to avoid SSR issues
const LiveChart = dynamic(() => import("@/components/LiveChart"), {
  ssr: false,
  loading: () => (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--text-muted)", letterSpacing: "0.08em" }}>
      Loading chart…
    </div>
  ),
});

const PortfolioChart = dynamic(() => import("@/components/PortfolioChart"), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const WS_URL = API.replace(/^http/, "ws") + "/ws/dashboard";

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

export interface TradeItem {
  id: string;
  ticker: string;
  action: string;
  amount: number;
  price: number;
  status: string;
  is_closed: boolean;
  created_at: string;
  updated_at?: string;
  pnl_usdt?: number;
}

interface LivePosition {
  id: string;
  ticker: string;
  action: string;
  entry_price: number;
  current_price: number;
  size_usdt: number;
  stop_loss: number;
  take_profit: number;
  unrealised_pnl: number;
  unrealised_pct: number;
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
    ws.onopen = () => { setConnected(true); reconnectDelay.current = 1000; };
    ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch { } };
    ws.onclose = () => {
      setConnected(false);
      setTimeout(() => { reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000); connect(); }, reconnectDelay.current);
    };
    ws.onerror = () => ws.close();
  }, [onMessage]);

  useEffect(() => { connect(); return () => wsRef.current?.close(); }, [connect]);
  return connected;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
const usdFormatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });

function formatUSD(value: number): string {
  return usdFormatter.format(value);
}

function timeAgo(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function formatPrice(price: number) {
  return price >= 1
    ? formatUSD(price)
    : `$${price.toFixed(6)}`;
}

function getSentimentColor(score: number | null): string {
  if (score === null) return "var(--text-muted)";
  if (score > 0.3) return "var(--green)";
  if (score < -0.3) return "var(--red)";
  return "var(--amber)";
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------
function StatCard({ label, value, sub, icon, valueColor }: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ReactNode;
  valueColor?: string;
}) {
  const flash = useFlash(value);
  return (
    <div style={{
      background: flash === "up" ? "rgba(16,185,129,0.05)" : flash === "down" ? "rgba(244,63,94,0.05)" : "var(--bg-card)",
      border: "1px solid var(--border)",
      borderRadius: "10px",
      padding: "20px",
      transition: "background 0.3s ease",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "14px" }}>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 500,
          letterSpacing: "0.1em", color: "var(--text-muted)", textTransform: "uppercase" as const,
        }}>
          {label}
        </span>
        <div style={{ color: "var(--text-muted)", opacity: 0.4 }}>
          {icon}
        </div>
      </div>
      <div className="tabular-nums" style={{
        fontFamily: "var(--font-mono)", fontSize: "24px", fontWeight: 600,
        color: valueColor || (flash === "up" ? "var(--green)" : flash === "down" ? "var(--red)" : "var(--text-primary)"),
        letterSpacing: "-0.02em", lineHeight: 1,
        transition: "color 0.3s ease",
      }}>
        {value}
      </div>
      {sub && (
        <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)", marginTop: "8px", letterSpacing: "0.02em" }}>
          {sub}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ManualTradeModal
// ---------------------------------------------------------------------------
function ManualTradeModal({ open, onClose, onRefresh }: { open: boolean; onClose: () => void; onRefresh: () => void }) {
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
      setToast({ msg: `${action} executed · ${data.order?.status || "OK"}`, ok: true });
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
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%", maxWidth: "400px", background: "var(--bg-surface)",
          border: "1px solid var(--border-hover)", borderRadius: "12px",
          padding: "24px", boxShadow: "0 24px 80px rgba(0,0,0,0.5)"
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: 600, letterSpacing: "0.1em", color: "var(--text-secondary)", textTransform: "uppercase" as const }}>Manual Trade</span>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-muted)", fontSize: "18px", lineHeight: 1, padding: "2px 6px" }}>×</button>
        </div>

        {/* Inputs */}
        <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginBottom: "16px" }}>
          <div style={{ position: "relative" }}>
            <span style={{ position: "absolute", left: "12px", top: "50%", transform: "translateY(-50%)", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em" }}>PAIR</span>
            <input type="text" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} style={{ width: "100%", paddingLeft: "52px", paddingRight: "12px", paddingTop: "12px", paddingBottom: "12px" }} />
          </div>
          <div style={{ position: "relative" }}>
            <span style={{ position: "absolute", left: "12px", top: "50%", transform: "translateY(-50%)", fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em" }}>USDT</span>
            <input type="number" value={amount} min="10" step="1" onChange={(e) => setAmount(e.target.value)} style={{ width: "100%", paddingLeft: "52px", paddingRight: "12px", paddingTop: "12px", paddingBottom: "12px" }} />
          </div>
        </div>

        {/* Toast */}
        {toast && (
          <div style={{
            padding: "8px 12px", borderRadius: "8px", marginBottom: "12px",
            fontFamily: "var(--font-mono)", fontSize: "11px",
            background: toast.ok ? "var(--green-dim)" : "var(--red-dim)",
            color: toast.ok ? "var(--green)" : "var(--red)"
          }}>
            {toast.msg}
          </div>
        )}

        {/* Buttons */}
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            onClick={() => execute("BUY")} disabled={busy !== null}
            style={{
              flex: 1, padding: "12px", borderRadius: "8px", fontFamily: "var(--font-mono)",
              fontSize: "12px", fontWeight: 600, letterSpacing: "0.06em",
              background: "var(--green-dim)", border: "1px solid rgba(16,185,129,0.15)",
              color: "var(--green)", opacity: busy !== null ? 0.5 : 1
            }}
          >
            {busy === "BUY" ? "Executing…" : "▲ Long"}
          </button>
          <button
            onClick={() => execute("SELL")} disabled={busy !== null}
            style={{
              flex: 1, padding: "12px", borderRadius: "8px", fontFamily: "var(--font-mono)",
              fontSize: "12px", fontWeight: 600, letterSpacing: "0.06em",
              background: "var(--red-dim)", border: "1px solid rgba(244,63,94,0.15)",
              color: "var(--red)", opacity: busy !== null ? 0.5 : 1
            }}
          >
            {busy === "SELL" ? "Executing…" : "▼ Short"}
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
    total_balance: 0, pnl_24h: 0, total_trades: 0, signals_processed: 0,
    holdings: [] as { coin: string; amount: number; value_usdt: number }[],
    exchanges_breakdown: {} as Record<string, any>,
    ai_efficiency: 0, burn_rate: 0, system_health: "ONLINE",
    total_invested: 0, active_leverage: 0, avg_leverage: 0,
    tokens_consumed: 0, ai_analysis_count: 0, api_calls: 0,
    market_trends: { "4h": "up", "1h": "flat", "15m": "down" },
    risk_radar: { price: 0, sl: 0, tp: 0 }
  });
  const [analytics, setAnalytics] = useState({
    total_trades: 0, win_rate: 0, total_pnl: 0, equity_curve: [] as any[]
  });
  const [adaptation, setAdaptation] = useState({
    score: 0, label: "Calibrating", win_rate: 0, total_trades: 0,
    details: {} as any
  });
  const [botState, setBotState] = useState<BotState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [tradeModalOpen, setTradeModalOpen] = useState(false);
  const [visibleNews, setVisibleNews] = useState(8);
  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [hasMounted, setHasMounted] = useState(false);
  const [livePositions, setLivePositions] = useState<LivePosition[]>([]);
  const [activeTab, setActiveTab] = useState<"positions" | "history">("positions");
  const isFetching = useRef(false);

  useEffect(() => { setHasMounted(true); }, []);

  const fetchData = useCallback(async () => {
    if (isFetching.current) return;
    isFetching.current = true;
    setLoading(true);
    setError(null);
    try {
      const fetchOpts = {
        cache: 'no-store' as const,
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Pragma': 'no-cache',
          'Expires': '0'
        }
      };
      const [newsRes, tradesRes, statsRes, analyticsRes, adaptationRes] = await Promise.all([
        fetch(`${API}/api/news?t=${Date.now()}`, fetchOpts),
        fetch(`${API}/api/trades?t=${Date.now()}`, fetchOpts),
        fetch(`${API}/api/stats?t=${Date.now()}`, fetchOpts),
        fetch(`${API}/api/analytics?t=${Date.now()}`, fetchOpts),
        fetch(`${API}/api/adaptation?t=${Date.now()}`, fetchOpts),
      ]);
      if (!newsRes.ok || !tradesRes.ok || !statsRes.ok || !analyticsRes.ok) throw new Error("API error");
      const [newsData, tradesData, statsData, analyticsData, adaptationData] = await Promise.all([
        newsRes.json(), tradesRes.json(), statsRes.json(), analyticsRes.json(), adaptationRes.ok ? adaptationRes.json() : Promise.resolve(null),
      ]);
      setNews(newsData); setTrades(tradesData); setStats(statsData); setAnalytics(analyticsData);
      if (adaptationData) setAdaptation(adaptationData);
      setLastRefresh(new Date());
    } catch {
      setError("Cannot reach backend — is the server running on :8000?");
    } finally {
      setLoading(false);
      isFetching.current = false;
    }
  }, []);

  const resetPaperTest = useCallback(async () => {
    if (!window.confirm("⚠️ This will WIPE all trades, positions, and news logs to start fresh at $10,000. Are you sure?")) return;
    setResetting(true);
    setResetMsg(null);
    try {
      const res = await fetch(`${API}/api/reset-paper-test`, { method: "POST" });
      const data = await res.json();
      if (data.status === "success") {
        setResetMsg({ ok: true, text: data.message });
        await fetchData();
      } else {
        setResetMsg({ ok: false, text: data.message || "Reset failed" });
      }
    } catch {
      setResetMsg({ ok: false, text: "Cannot reach backend" });
    } finally {
      setResetting(false);
      setTimeout(() => setResetMsg(null), 5000);
    }
  }, [fetchData]);

  const handleWsMessage = useCallback((msg: Record<string, unknown>) => {
    if (msg.type === "bot_state") {
      setBotState(msg as unknown as BotState);
      setError(null);
    }
    if (msg.type === "trade_closed") fetchData();
    if (msg.type === "bot_state" && typeof msg.last_action === "string" && msg.last_action !== "None") fetchData();
  }, [fetchData]);

  const wsConnected = useDashboardWS(handleWsMessage);

  // Live positions polling
  const fetchLivePositions = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/positions/live?t=${Date.now()}`, {
        cache: 'no-store',
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Pragma': 'no-cache',
          'Expires': '0'
        }
      });
      if (res.ok) { const data = await res.json(); setLivePositions(data.positions || []); }
    } catch { /* silent fail */ }
  }, []);

  useEffect(() => { fetchLivePositions(); }, [fetchLivePositions]);
  useEffect(() => { const i = setInterval(fetchLivePositions, 15_000); return () => clearInterval(i); }, [fetchLivePositions]);
  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { const i = setInterval(fetchData, 30_000); return () => clearInterval(i); }, [fetchData]);

  const openPositions = useMemo(() => trades.filter((t) => !t.is_closed && t.action === "BUY"), [trades]);
  const tradeHistory = useMemo(() => trades.filter((t) => t.is_closed || t.action === "SELL"), [trades]);

  const uptime = useMemo(() => {
    if (!botState?.started_at) return "—";
    const ms = Date.now() - new Date(botState.started_at).getTime();
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    return `${h}h ${m}m`;
  }, [botState]);

  return (
    <>
      <ManualTradeModal open={tradeModalOpen} onClose={() => setTradeModalOpen(false)} onRefresh={fetchData} />

      <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>

        {/* ── Header ───────────────────────────────────────────────── */}
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
              <h1 style={{ fontSize: "22px", fontWeight: 600, letterSpacing: "-0.02em", color: "var(--text-primary)", margin: 0 }}>
                Dashboard
              </h1>
              {/* WS status */}
              <div style={{
                display: "flex", alignItems: "center", gap: "5px",
                padding: "3px 10px", borderRadius: "20px",
                background: wsConnected ? "var(--green-dim)" : "var(--amber-dim)",
                fontFamily: "var(--font-mono)", fontSize: "9px", fontWeight: 600,
                letterSpacing: "0.08em", textTransform: "uppercase" as const,
                color: wsConnected ? "var(--green)" : "var(--amber)"
              }}>
                <span style={{ width: "5px", height: "5px", borderRadius: "50%", background: "currentColor" }} />
                {wsConnected ? "Live" : "Reconnecting"}
              </div>
            </div>
            <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)", margin: 0, letterSpacing: "0.03em" }}>
              {lastRefresh && hasMounted ? `Synced · ${timeAgo(lastRefresh.toISOString())}` : "Connecting…"}
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <button
              onClick={fetchData} disabled={loading}
              style={{
                display: "flex", alignItems: "center", gap: "6px",
                padding: "7px 14px", borderRadius: "8px",
                background: "var(--bg-card)", border: "1px solid var(--border)",
                fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.06em",
                color: loading ? "var(--text-muted)" : "var(--text-secondary)",
                textTransform: "uppercase" as const, opacity: loading ? 0.6 : 1
              }}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ animation: loading ? "spin 1s linear infinite" : "none" }}>
                <path d="M1 6a5 5 0 1 0 5-5" strokeLinecap="round" />
                <path d="M1 2v4h4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {loading ? "Syncing" : "Refresh"}
            </button>
            <button
              onClick={resetPaperTest} disabled={resetting}
              title="Wipe all trades and logs — start fresh at $10,000"
              style={{
                display: "flex", alignItems: "center", gap: "6px",
                padding: "7px 14px", borderRadius: "8px",
                background: "var(--red-dim)", border: "1px solid rgba(244,63,94,0.12)",
                fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.06em",
                color: "var(--red)", textTransform: "uppercase" as const, opacity: resetting ? 0.6 : 1,
              }}
            >
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 2l7 7M9 2l-7 7" strokeLinecap="round" />
              </svg>
              {resetting ? "Clearing…" : "Reset"}
            </button>
          </div>
        </div>

        {/* Reset feedback banner */}
        {resetMsg && (
          <div style={{
            display: "flex", alignItems: "center", gap: "10px",
            padding: "10px 16px", borderRadius: "8px",
            background: resetMsg.ok ? "var(--green-dim)" : "var(--red-dim)",
            fontFamily: "var(--font-mono)", fontSize: "11px",
            color: resetMsg.ok ? "var(--green)" : "var(--red)"
          }}>
            {resetMsg.ok ? "✓" : "✗"} {resetMsg.text}
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div style={{
            display: "flex", alignItems: "center", gap: "10px",
            padding: "12px 16px", borderRadius: "8px",
            background: "var(--red-dim)",
            fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--red)"
          }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M7 0a7 7 0 1 0 0 14A7 7 0 0 0 7 0zm0 10a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm0-7a1 1 0 0 1 1 1v4a1 1 0 0 1-2 0V4a1 1 0 0 1 1-1z" /></svg>
            {error}
          </div>
        )}

        {/* ── Zone 1: KPI Strip ──────────────────────────────────── */}
        <div className="kpi-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "16px" }}>
          <StatCard
            label="Portfolio Balance"
            value={formatUSD(stats.total_balance)}
            sub={
              stats.exchanges_breakdown && Object.keys(stats.exchanges_breakdown).length > 0
                ? Object.entries(stats.exchanges_breakdown)
                    .map(([ex, data]: [string, any]) => `${ex}: ${formatUSD(data.USDT)}`)
                    .join(" · ")
                : "Aggregated balance"
            }
            icon={<DollarSign size={15} />}
          />
          <StatCard
            label="Realized PnL"
            value={stats.pnl_24h >= 0 ? `+${formatUSD(stats.pnl_24h)}` : formatUSD(stats.pnl_24h)}
            sub={`${stats.total_trades} closed trades`}
            valueColor={stats.pnl_24h >= 0 ? "var(--green)" : "var(--red)"}
            icon={stats.pnl_24h >= 0 ? <TrendingUp size={15} /> : <TrendingDown size={15} />}
          />
          <StatCard
            label="Open Positions"
            value={String(openPositions.length)}
            sub={`${livePositions.length} live tracked`}
            icon={<Shield size={15} />}
          />
          <StatCard
            label="System Status"
            value={error ? "Offline" : stats.system_health}
            sub={error ? "Backend unreachable" : `${stats.signals_processed} signals processed`}
            valueColor={error ? "var(--red)" : "var(--green)"}
            icon={<Zap size={15} />}
          />
        </div>

        {/* ── Zone 2: Workspace (Chart + Sidebar) ────────────────── */}
        <div className="workspace-grid" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "16px", minHeight: "520px" }}>

          {/* ── Chart (primary) ──────────────────────────────────── */}
          <div style={{
            background: "var(--bg-card)", border: "1px solid var(--border)",
            borderRadius: "10px", overflow: "hidden",
            display: "flex", flexDirection: "column",
          }}>
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "10px 16px", borderBottom: "1px solid var(--border)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span className="pulse-soft" style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>BTC/USDT</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)" }}>Binance</span>
              </div>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)", letterSpacing: "0.06em" }}>1H</span>
            </div>
            <div style={{ flex: 1, width: "100%", minHeight: 0 }}>
              <LiveChart trades={trades} />
            </div>
          </div>

          {/* ── Right Sidebar ───────────────────────────────────── */}
          <div style={{ display: "flex", flexDirection: "column", gap: "16px", minWidth: 0 }}>

            {/* AI Engine Status */}
            {botState && (
              <div style={{
                background: "var(--bg-card)", border: "1px solid var(--border)",
                borderRadius: "10px", padding: "16px",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
                  <span className="pulse-soft" style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--green)", display: "inline-block" }} />
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 600, letterSpacing: "0.1em", color: "var(--text-secondary)", textTransform: "uppercase" as const }}>AI Engine</span>
                </div>
                <p style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-primary)", margin: "0 0 4px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {botState.status}
                </p>
                <p style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)", margin: "0 0 12px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {botState.last_action} · {hasMounted ? uptime : "—"} uptime
                </p>
                {/* Confidence bar */}
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" as const }}>Confidence</span>
                    <span className="tabular-nums" style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-secondary)", fontWeight: 600 }}>{stats.ai_efficiency.toFixed(1)}%</span>
                  </div>
                  <div style={{ width: "100%", height: "3px", background: "rgba(255,255,255,0.05)", borderRadius: "2px", overflow: "hidden" }}>
                    <div style={{ width: `${stats.ai_efficiency}%`, height: "100%", background: "var(--green)", transition: "width 1s ease", borderRadius: "2px" }} />
                  </div>
                </div>
                {/* Adaptation bar */}
                <div style={{ marginTop: "10px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" as const }}>Adaptation</span>
                    <span className="tabular-nums" style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-secondary)", fontWeight: 600 }}>{adaptation.score}% · {adaptation.label}</span>
                  </div>
                  <div style={{ width: "100%", height: "3px", background: "rgba(255,255,255,0.05)", borderRadius: "2px", overflow: "hidden" }}>
                    <div style={{
                      width: `${adaptation.score}%`, height: "100%", borderRadius: "2px",
                      background: adaptation.score >= 80 ? "var(--green)" : adaptation.score >= 55 ? "var(--text-secondary)" : "var(--amber)",
                      transition: "width 1s ease",
                    }} />
                  </div>
                </div>
              </div>
            )}

            {/* News Sentiment Feed */}
            <div style={{
              background: "var(--bg-card)", border: "1px solid var(--border)",
              borderRadius: "10px", overflow: "hidden",
              display: "flex", flexDirection: "column", flex: 1, minHeight: 0,
            }}>
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "12px 16px", borderBottom: "1px solid var(--border)", flexShrink: 0,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>News</span>
                  <span className="tabular-nums" style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)" }}>{news.length}</span>
                </div>
              </div>

              <div style={{ overflowY: "auto", flex: 1 }}>
                {loading ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                    {[...Array(4)].map((_, i) => (
                      <div key={i} style={{ display: "flex", gap: "10px", padding: "12px 16px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                        <div className="shimmer" style={{ width: "32px", height: "32px", borderRadius: "6px", flexShrink: 0 }} />
                        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
                          <div className="shimmer" style={{ height: "10px", borderRadius: "3px", width: "80%" }} />
                          <div className="shimmer" style={{ height: "10px", borderRadius: "3px", width: "50%" }} />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : news.length === 0 ? (
                  <div style={{ padding: "32px 16px", textAlign: "center", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)" }}>
                    No signals yet
                  </div>
                ) : (
                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                    {news.slice(0, visibleNews).map((s) => (
                      <li key={s.id} style={{
                        display: "flex", gap: "10px", padding: "10px 16px",
                        borderBottom: "1px solid rgba(255,255,255,0.04)",
                        transition: "background 0.1s ease",
                      }}>
                        {/* Ticker */}
                        <div style={{
                          width: "32px", height: "32px", borderRadius: "6px", flexShrink: 0,
                          background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontFamily: "var(--font-mono)", fontSize: "9px", fontWeight: 600,
                          color: "var(--text-secondary)", letterSpacing: "0.03em"
                        }}>
                          {s.ticker ?? "?"}
                        </div>
                        {/* Content */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <p style={{ fontSize: "11px", color: "var(--text-secondary)", margin: "0 0 4px", lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                            {s.raw_text}
                          </p>
                          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            {s.sentiment_score !== null && (
                              <span className="tabular-nums" style={{
                                fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 600,
                                padding: "1px 5px", borderRadius: "3px",
                                background: s.sentiment_score > 0 ? "var(--green-dim)" : s.sentiment_score < 0 ? "var(--red-dim)" : "var(--amber-dim)",
                                color: getSentimentColor(s.sentiment_score),
                              }}>
                                {s.sentiment_score > 0 ? "+" : ""}{s.sentiment_score.toFixed(2)}
                              </span>
                            )}
                            {s.confidence !== null && (
                              <span className="tabular-nums" style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)" }}>{s.confidence}%</span>
                            )}
                            <span className="tabular-nums" style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)", marginLeft: "auto" }}>{timeAgo(s.created_at)}</span>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {/* Equity Curve */}
            <div style={{
              background: "var(--bg-card)", border: "1px solid var(--border)",
              borderRadius: "10px", padding: "16px", minHeight: "180px",
              display: "flex", flexDirection: "column",
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
                <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>Portfolio</span>
                <span className="tabular-nums" style={{
                  fontFamily: "var(--font-mono)", fontSize: "10px",
                  color: stats.pnl_24h >= 0 ? "var(--green)" : "var(--red)"
                }}>
                  {stats.pnl_24h >= 0 ? "+" : ""}{((stats.pnl_24h / (stats.total_balance - stats.pnl_24h || 1000)) * 100).toFixed(2)}%
                </span>
              </div>
              <div style={{ flex: 1, minHeight: "120px" }}>
                <PortfolioChart currentBalance={stats.total_balance} equityCurve={analytics.equity_curve} />
              </div>
            </div>
          </div>
        </div>

        {/* ── Zone 3: Tables ─────────────────────────────────────── */}
        <div style={{
          background: "var(--bg-card)", border: "1px solid var(--border)",
          borderRadius: "10px", overflow: "hidden",
        }}>
          {/* Tab bar */}
          <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
            <button
              onClick={() => setActiveTab("positions")}
              style={{
                padding: "12px 20px", background: "none", border: "none",
                borderBottom: activeTab === "positions" ? "2px solid var(--text-primary)" : "2px solid transparent",
                fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: activeTab === "positions" ? 600 : 400,
                letterSpacing: "0.06em", textTransform: "uppercase" as const,
                color: activeTab === "positions" ? "var(--text-primary)" : "var(--text-muted)",
                transition: "all 0.15s ease",
              }}
            >
              Active Positions
              {(livePositions.length > 0 || openPositions.length > 0) && (
                <span className="tabular-nums" style={{
                  marginLeft: "8px", padding: "1px 6px", borderRadius: "3px",
                  fontSize: "10px", background: "var(--green-dim)", color: "var(--green)"
                }}>
                  {livePositions.length || openPositions.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("history")}
              style={{
                padding: "12px 20px", background: "none", border: "none",
                borderBottom: activeTab === "history" ? "2px solid var(--text-primary)" : "2px solid transparent",
                fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: activeTab === "history" ? 600 : 400,
                letterSpacing: "0.06em", textTransform: "uppercase" as const,
                color: activeTab === "history" ? "var(--text-primary)" : "var(--text-muted)",
                transition: "all 0.15s ease",
              }}
            >
              Trade History
              <span className="tabular-nums" style={{ marginLeft: "8px", fontSize: "10px", color: "var(--text-muted)" }}>{tradeHistory.length}</span>
            </button>
          </div>

          {/* Table content */}
          <div style={{ overflowX: "auto" }}>
            {activeTab === "positions" ? (
              <table>
                <thead>
                  <tr>
                    {["Ticker", "Entry", "Current", "PnL", "SL", "TP", "Status"].map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(livePositions.length > 0 ? livePositions : []).map((t) => {
                    const pnlPos = t.unrealised_pnl >= 0;
                    const sign = pnlPos ? "+" : "";
                    return (
                      <tr key={t.id}>
                        <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                          {t.ticker} <span style={{ fontSize: "9px", color: "var(--text-muted)" }}>{t.action}</span>
                        </td>
                        <td className="tabular-nums" style={{ color: "var(--text-data)" }}>{formatPrice(t.entry_price)}</td>
                        <td className="tabular-nums" style={{ color: "var(--text-primary)", fontWeight: 600 }}>{formatPrice(t.current_price)}</td>
                        <td className="tabular-nums" style={{ color: pnlPos ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
                          {sign}{t.unrealised_pnl.toFixed(2)} ({sign}{t.unrealised_pct.toFixed(2)}%)
                        </td>
                        <td className="tabular-nums" style={{ color: "var(--red)", fontSize: "11px" }}>{formatPrice(t.stop_loss)}</td>
                        <td className="tabular-nums" style={{ color: "var(--green)", fontSize: "11px" }}>{formatPrice(t.take_profit)}</td>
                        <td>
                          <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                            <span className="pulse-soft" style={{ width: "5px", height: "5px", borderRadius: "50%", background: "var(--green)" }} />
                            <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--green)" }}>Live</span>
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                  {livePositions.length === 0 && openPositions.length === 0 && (
                    <tr>
                      <td colSpan={7} style={{ textAlign: "center", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)", padding: "32px 16px" }}>
                        No open positions
                      </td>
                    </tr>
                  )}
                  {livePositions.length === 0 && openPositions.length > 0 && openPositions.map((t) => (
                    <tr key={t.id}>
                      <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>{t.ticker}</td>
                      <td className="tabular-nums" style={{ color: "var(--text-data)" }}>{formatPrice(t.price)}</td>
                      <td style={{ color: "var(--text-muted)" }}>—</td>
                      <td style={{ color: "var(--text-muted)" }}>—</td>
                      <td style={{ color: "var(--text-muted)" }}>—</td>
                      <td style={{ color: "var(--text-muted)" }}>—</td>
                      <td>
                        <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                          <span className="pulse-soft" style={{ width: "5px", height: "5px", borderRadius: "50%", background: "var(--green)" }} />
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--green)" }}>Holding</span>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table>
                <thead>
                  <tr>
                    {["Ticker", "Side", "Amount", "Price", "Time", "Status"].map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tradeHistory.map((t) => (
                    <tr key={t.id}>
                      <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>{t.ticker}</td>
                      <td>
                        <span style={{
                          fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 600,
                          padding: "2px 7px", borderRadius: "4px",
                          background: t.action.toUpperCase() === "BUY" ? "var(--green-dim)" : "var(--red-dim)",
                          color: t.action.toUpperCase() === "BUY" ? "var(--green)" : "var(--red)",
                        }}>
                          {t.action.toUpperCase() === "BUY" ? "▲ Long" : "▼ Short"}
                        </span>
                      </td>
                      <td className="tabular-nums">{Number(t.amount).toFixed(4)}</td>
                      <td className="tabular-nums" style={{ color: "var(--text-primary)" }}>{formatPrice(t.price)}</td>
                      <td className="tabular-nums" style={{ color: "var(--text-muted)" }}>{timeAgo(t.created_at)}</td>
                      <td>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)" }}>Closed</span>
                      </td>
                    </tr>
                  ))}
                  {tradeHistory.length === 0 && (
                    <tr>
                      <td colSpan={6} style={{ textAlign: "center", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)", padding: "32px 16px" }}>
                        No trade history
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* ── Floating Action Button ──────────────────────────────── */}
      <button
        id="manual-trade-btn"
        onClick={() => setTradeModalOpen(true)}
        style={{
          position: "fixed", bottom: "24px", right: "24px", zIndex: 40,
          display: "flex", alignItems: "center", gap: "8px",
          padding: "10px 18px", borderRadius: "40px",
          background: "var(--text-primary)", border: "none", color: "var(--bg-base)",
          fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 600,
          letterSpacing: "0.04em",
          boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
        }}
        title="Open Manual Trade"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M7 1v12M1 7h12" />
        </svg>
        New Trade
      </button>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @media (max-width: 1100px) {
          .workspace-grid { grid-template-columns: 1fr !important; }
          .kpi-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
        @media (max-width: 640px) {
          .kpi-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </>
  );
}
