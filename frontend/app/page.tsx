"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useCallback, useRef, useMemo, Suspense } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, MeshDistortMaterial, PerspectiveCamera } from "@react-three/drei";
import * as THREE from "three";
import { motion, AnimatePresence, useSpring, useTransform } from "framer-motion";
import {
  TrendingUp, TrendingDown, Activity, DollarSign, Cpu, Zap,
  Shield, Target, Calendar, MessageSquare, Send, ZapOff,
  ChevronRight, ArrowUpRight, ArrowDownRight
} from "lucide-react";

// Dynamically import the chart to avoid SSR issues
const LiveChart = dynamic(() => import("@/components/LiveChart"), {
  ssr: false,
  loading: () => (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-jetbrains)", fontSize: "12px", color: "var(--text-muted)", letterSpacing: "0.1em" }}>
      LOADING CHART…
    </div>
  ),
});

const PortfolioChart = dynamic(() => import("@/components/PortfolioChart"), { ssr: false });
const WinRateChart = dynamic(() => import("@/components/WinRateChart"), { ssr: false });

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

function getSentimentColor(score: number | null): string {
  if (score === null) return "var(--text-muted)";
  if (score > 0.3) return "var(--green)";
  if (score < -0.3) return "var(--red)";
  return "var(--amber)";
}

// ---------------------------------------------------------------------------
// Animated Number
// ---------------------------------------------------------------------------
function AnimatedNumber({ value }: { value: number }) {
  const springValue = useSpring(0, { stiffness: 60, damping: 20 });
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    springValue.set(value);
  }, [value, springValue]);

  useEffect(() => {
    const unsubscribe = springValue.on("change", (v) => {
      setDisplayValue(v);
    });
    return () => unsubscribe();
  }, [springValue]);

  return <span>{displayValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>;
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------
function StatCard({
  label, value, rawValue, sub, accentColor, icon, pulse = false, animate = false
}: {
  label: string;
  value: string;
  rawValue?: number;
  sub?: string;
  accentColor: string;
  icon: React.ReactNode;
  pulse?: boolean;
  animate?: boolean;
}) {
  const flash = useFlash(value);
  return (
    <motion.div
      whileHover={{ scale: 1.02, y: -4 }}
      transition={{ type: "spring", stiffness: 400, damping: 10 }}
      className="glass-card"
      style={{
        background: flash === "up" ? "rgba(34,197,94,0.1)" : flash === "down" ? "rgba(239,68,68,0.1)" : "var(--glass-bg)",
        borderColor: flash === "up" ? "rgba(34,197,94,0.4)" : flash === "down" ? "rgba(239,68,68,0.4)" : "var(--glass-border)",
        borderRadius: "12px",
        padding: "20px",
        position: "relative",
        overflow: "hidden",
        transition: "background 0.3s ease, border-color 0.3s ease",
      }}
    >
      {/* Accent glow blob */}
      <div style={{
        position: "absolute", top: -24, left: -24, width: "80px", height: "80px",
        borderRadius: "50%", background: accentColor, filter: "blur(28px)", opacity: 0.15,
        pointerEvents: "none"
      }} />

      {/* Top row: icon + label */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
        <span style={{
          fontFamily: "var(--font-jetbrains)", fontSize: "9px", fontWeight: 500,
          letterSpacing: "0.18em", color: "var(--text-muted)", textTransform: "uppercase"
        }}>
          {label}
        </span>
        <div style={{
          width: "28px", height: "28px", borderRadius: "6px",
          background: "rgba(255,255,255,0.04)", border: "1px solid var(--border)",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: accentColor,
        }}>
          {icon}
        </div>
      </div>

      {/* Value */}
      <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
        <span style={{
          fontFamily: "var(--font-jetbrains)", fontSize: "26px", fontWeight: 700,
          letterSpacing: "-0.02em", lineHeight: 1,
          color: flash === "up" ? "var(--green)" : flash === "down" ? "var(--red)" : "var(--text-primary)",
          transition: "color 0.4s ease",
        }}>
          {animate && rawValue !== undefined ? <AnimatedNumber value={rawValue} /> : value}
        </span>
        {pulse && (
          <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            <span className="pulse-dot green" style={{ width: "6px", height: "6px" }} />
          </span>
        )}
      </div>

      {sub && (
        <p style={{
          fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)",
          marginTop: "4px", letterSpacing: "0.02em"
        }}>
          {sub}
        </p>
      )}

      {/* Hover Cyan Glow */}
      <motion.div
        initial={{ opacity: 0 }}
        whileHover={{ opacity: 1 }}
        style={{
          position: "absolute", inset: 0,
          boxShadow: `inset 0 0 20px ${accentColor}20`,
          pointerEvents: "none"
        }}
      />
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// TrendBar
// ---------------------------------------------------------------------------
function TrendBar({ label, timeframe, trend }: { label: string; timeframe: string; trend: "up" | "down" | "flat" }) {
  return (
    <div style={{ flex: 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
        <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em" }}>{timeframe}</span>
        <span style={{
          fontFamily: "var(--font-jetbrains)", fontSize: "9px",
          color: trend === "up" ? "var(--green)" : trend === "down" ? "var(--red)" : "var(--amber)",
          fontWeight: 700
        }}>
          {trend.toUpperCase()}
        </span>
      </div>
      <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.05)", borderRadius: "2px", overflow: "hidden" }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: "100%" }}
          style={{
            height: "100%",
            background: trend === "up" ? "var(--green)" : trend === "down" ? "var(--red)" : "var(--amber)",
            boxShadow: `0 0 8px ${trend === "up" ? "var(--green)" : trend === "down" ? "var(--red)" : "var(--amber)"}80`
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RiskRadarGauge
// ---------------------------------------------------------------------------
function RiskRadarGauge({ currentPrice, sl, tp }: { currentPrice: number; sl: number; tp: number }) {
  const range = tp - sl;
  const progress = Math.min(Math.max((currentPrice - sl) / range, 0), 1);
  const angle = progress * 180 - 90; // -90 to 90 degrees

  // Calculate dot position on arc (radius 60, center 80,70)
  const rad = (progress * 180 - 180) * (Math.PI / 180);
  const dotX = 80 + 60 * Math.cos(rad);
  const dotY = 70 + 60 * Math.sin(rad);

  return (
    <div style={{ position: "relative", width: "100%", height: "140px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
      <svg width="180" height="100" viewBox="0 0 160 80" style={{ overflow: "visible" }}>
        {/* Background arcs */}
        <path d="M 10 70 A 60 60 0 0 1 150 70" fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth="1" />
        <path d="M 30 70 A 40 40 0 0 1 130 70" fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth="1" />

        {/* Main tracking arc */}
        <path d="M 10 70 A 60 60 0 0 1 150 70" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="10" strokeLinecap="round" />
        <motion.path
          d="M 10 70 A 60 60 0 0 1 150 70"
          fill="none"
          stroke="var(--cyan)"
          strokeWidth="10"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: progress }}
          transition={{ duration: 1.5, ease: "easeOut" }}
          style={{ filter: "drop-shadow(0 0 8px var(--cyan))", opacity: 0.8 }}
        />

        {/* Glow Dot */}
        <motion.circle
          cx={dotX}
          cy={dotY}
          r="4"
          fill="var(--cyan)"
          animate={{ cx: dotX, cy: dotY }}
          transition={{ type: "spring", stiffness: 100 }}
          style={{ filter: "drop-shadow(0 0 12px var(--cyan))" }}
        />
      </svg>

      {/* Needle */}
      <motion.div
        style={{
          position: "absolute", bottom: "40px", left: "50%",
          width: "2px", height: "55px", background: "linear-gradient(to top, var(--text-muted), #fff)",
          originY: "100%", x: "-50%",
          rotate: angle,
          zIndex: 2,
          boxShadow: "0 0 15px rgba(255,255,255,0.3)"
        }}
        animate={{ rotate: angle }}
        transition={{ type: "spring", stiffness: 60, damping: 12 }}
      />

      {/* Pivot Point */}
      <div style={{
        position: "absolute", bottom: "35px", left: "50%", transform: "translateX(-50%)",
        width: "10px", height: "10px", borderRadius: "50%", background: "#fff",
        border: "2px solid var(--bg-card)", zIndex: 3, boxShadow: "0 0 10px rgba(0,0,0,0.5)"
      }} />

      <div style={{ marginTop: "10px", textAlign: "center" }}>
        <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "14px", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
          {formatPrice(currentPrice)}
        </p>
        <div style={{ display: "flex", gap: "10px", justifyContent: "center", marginTop: "2px" }}>
          <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--red)", opacity: 0.8 }}>SL: {formatPrice(sl)}</span>
          <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--green)", opacity: 0.8 }}>TP: {formatPrice(tp)}</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PnLCalendar
// ---------------------------------------------------------------------------
function PnLCalendar({ analytics }: { analytics: { equity_curve: { date: string, trade_pnl: number }[] } }) {
  const [days, setDays] = useState<{ day: number; pnl: number; realPnl: number }[]>([]);

  useEffect(() => {
    const generatedDays = Array.from({ length: 98 }, (_, i) => ({ day: i, pnl: 0, realPnl: 0 }));
    
    const now = new Date();
    now.setHours(0,0,0,0);

    if (analytics?.equity_curve) {
      analytics.equity_curve.forEach((t: any) => {
          const tradeDate = new Date(t.date);
          tradeDate.setHours(0,0,0,0);
          const diffTime = now.getTime() - tradeDate.getTime();
          const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
          
          if (diffDays >= 0 && diffDays < 98) {
              const idx = 97 - diffDays;
              if (generatedDays[idx]) {
                  generatedDays[idx].realPnl += t.trade_pnl;
              }
          }
      });
    }

    const finalDays = generatedDays.map((d: any) => {
        let score = 0;
        if (d.realPnl > 50) score = 2;
        else if (d.realPnl > 0) score = 1;
        else if (d.realPnl < -50) score = -2;
        else if (d.realPnl < 0) score = -1;
        return { day: d.day, pnl: score, realPnl: d.realPnl };
    });

    setDays(finalDays);
  }, [analytics]);

  const getPnlColor = (pnl: number) => {
    if (pnl === 2) return "#22c55e";
    if (pnl === 1) return "rgba(34, 197, 94, 0.4)";
    if (pnl === -2) return "#ef4444";
    if (pnl === -1) return "rgba(239, 68, 68, 0.4)";
    return "rgba(255, 255, 255, 0.03)";
  };

  if (days.length === 0) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(14, 1fr)", gap: "3px", width: "100%" }}>
        {Array.from({ length: 98 }).map((_, i) => (
          <div key={i} style={{ aspectRatio: "1/1", borderRadius: "1px", background: "rgba(255, 255, 255, 0.03)" }} />
        ))}
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(14, 1fr)", gap: "3px", width: "100%" }}>
      {days.map((d, i) => (
        <motion.div
          key={i}
          whileHover={{ scale: 1.4, zIndex: 10, outline: "1px solid rgba(255,255,255,0.2)" }}
          style={{
            aspectRatio: "1/1",
            borderRadius: "1px",
            background: getPnlColor(d.pnl),
            cursor: "pointer",
            transition: "background 0.3s ease"
          }}
          title={d.pnl > 0 ? `Profit: $${d.realPnl.toFixed(2)}` : d.pnl < 0 ? `Loss: $${Math.abs(d.realPnl).toFixed(2)}` : "No Activity"}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3D Background
// ---------------------------------------------------------------------------
function AnimatedShape() {
  const meshRef = useRef<THREE.Mesh>(null);
  useFrame((state) => {
    if (meshRef.current) {
      meshRef.current.rotation.x = state.clock.getElapsedTime() * 0.2;
      meshRef.current.rotation.y = state.clock.getElapsedTime() * 0.3;
    }
  });

  return (
    <Float speed={2} rotationIntensity={1} floatIntensity={1}>
      <mesh ref={meshRef}>
        <icosahedronGeometry args={[2, 1]} />
        <MeshDistortMaterial color="#00d4ff" speed={2} distort={0.3} wireframe />
      </mesh>
    </Float>
  );
}

function Dashboard3D() {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: -1, pointerEvents: "none", opacity: 0.4 }}>
      <Canvas>
        <PerspectiveCamera makeDefault position={[0, 0, 8]} />
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} intensity={1} />
        <Suspense fallback={null}>
          <AnimatedShape />
        </Suspense>
      </Canvas>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Copilot Interface
// ---------------------------------------------------------------------------
function CopilotInterface() {
  const [input, setInput] = useState("");
  const chips = [
    { label: "Analyze SOL", icon: <Zap size={12} /> },
    { label: "Close Risks", icon: <Shield size={12} /> },
    { label: "Today's summary", icon: <Calendar size={12} /> }
  ];

  return (
    <div className="glass-card" style={{ padding: "20px", display: "flex", flexDirection: "column", gap: "16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "var(--cyan-dim)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--cyan)" }}>
          <MessageSquare size={18} />
        </div>
        <span style={{ fontFamily: "var(--font-syne)", fontSize: "14px", fontWeight: 700 }}>AI Copilot</span>
        <span className="pulse-dot cyan" />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
        {chips.map((chip, i) => (
          <motion.div
            key={i}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            style={{
              padding: "6px 12px", borderRadius: "20px", background: "var(--bg-surface)",
              border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: "6px",
              cursor: "pointer", fontSize: "11px", fontFamily: "var(--font-jetbrains)"
            }}
          >
            <span style={{ color: "var(--cyan)" }}>{chip.icon}</span>
            <span>{chip.label}</span>
            <span className="animate-pulse" style={{ width: "4px", height: "4px", borderRadius: "50%", background: "var(--cyan)" }} />
          </motion.div>
        ))}
      </div>

      <div style={{ position: "relative" }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask GrokSniper anything..."
          style={{ width: "100%", padding: "12px 16px", paddingRight: "44px", background: "rgba(255,255,255,0.03)" }}
        />
        <motion.button
          whileHover={{ scale: 1.1, color: "var(--cyan)" }}
          style={{ position: "absolute", right: "12px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "var(--text-muted)" }}
        >
          <Send size={18} />
        </motion.button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Manual Trade Modal
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
      style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "flex-end", justifyContent: "center", padding: "16px", background: "rgba(0,0,0,0.75)", backdropFilter: "blur(8px)" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%", maxWidth: "420px", background: "var(--bg-card)",
          border: "1px solid var(--border-cyan)", borderRadius: "16px",
          padding: "24px", boxShadow: "0 0 60px rgba(0,212,255,0.1), 0 24px 80px rgba(0,0,0,0.6)"
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ color: "var(--cyan)" }}>
              <path d="M8 1L10.5 6H15L11.5 9.5L13 15L8 12L3 15L4.5 9.5L1 6H5.5L8 1Z" fill="currentColor" fillOpacity="0.8" />
            </svg>
            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", fontWeight: 700, letterSpacing: "0.12em", color: "var(--cyan)", textTransform: "uppercase" }}>Manual Execution</span>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-muted)", fontSize: "18px", lineHeight: 1, padding: "2px 6px" }}>×</button>
        </div>

        {/* Inputs */}
        <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginBottom: "16px" }}>
          <div style={{ position: "relative" }}>
            <span style={{ position: "absolute", left: "12px", top: "50%", transform: "translateY(-50%)", fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em" }}>PAIR</span>
            <input
              type="text" value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              style={{ width: "100%", paddingLeft: "52px", paddingRight: "12px", paddingTop: "12px", paddingBottom: "12px" }}
            />
          </div>
          <div style={{ position: "relative" }}>
            <span style={{ position: "absolute", left: "12px", top: "50%", transform: "translateY(-50%)", fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em" }}>USDT</span>
            <input
              type="number" value={amount} min="10" step="1"
              onChange={(e) => setAmount(e.target.value)}
              style={{ width: "100%", paddingLeft: "52px", paddingRight: "12px", paddingTop: "12px", paddingBottom: "12px" }}
            />
          </div>
        </div>

        {/* Toast */}
        {toast && (
          <div style={{
            padding: "8px 12px", borderRadius: "8px", marginBottom: "12px",
            fontFamily: "var(--font-jetbrains)", fontSize: "11px",
            background: toast.ok ? "var(--green-dim)" : "var(--red-dim)",
            border: `1px solid ${toast.ok ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}`,
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
              flex: 1, padding: "12px", borderRadius: "8px", fontFamily: "var(--font-jetbrains)",
              fontSize: "12px", fontWeight: 700, letterSpacing: "0.08em",
              background: "var(--green-dim)", border: "1px solid rgba(34,197,94,0.3)",
              color: "var(--green)", opacity: busy !== null ? 0.5 : 1
            }}
          >
            {busy === "BUY" ? "EXECUTING…" : "▲ LONG"}
          </button>
          <button
            onClick={() => execute("SELL")} disabled={busy !== null}
            style={{
              flex: 1, padding: "12px", borderRadius: "8px", fontFamily: "var(--font-jetbrains)",
              fontSize: "12px", fontWeight: 700, letterSpacing: "0.08em",
              background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.3)",
              color: "var(--red)", opacity: busy !== null ? 0.5 : 1
            }}
          >
            {busy === "SELL" ? "EXECUTING…" : "▼ SHORT"}
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
    ai_efficiency: 0, burn_rate: 0, system_health: "ONLINE",
    total_invested: 0, active_leverage: 0, avg_leverage: 0,
    tokens_consumed: 0, ai_analysis_count: 0, api_calls: 0
  });
  const [analytics, setAnalytics] = useState({
    total_trades: 0, win_rate: 0, total_pnl: 0, equity_curve: [] as any[]
  });
  const [botState, setBotState] = useState<BotState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [tradeModalOpen, setTradeModalOpen] = useState(false);
  const [visibleNews, setVisibleNews] = useState(6);
  const [visiblePositions, setVisiblePositions] = useState(5);
  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [hasMounted, setHasMounted] = useState(false);
  const isFetching = useRef(false);

  useEffect(() => {
    setHasMounted(true);
  }, []);

  const fetchData = useCallback(async () => {
    if (isFetching.current) return;
    isFetching.current = true;
    setLoading(true);
    setError(null);
    try {
      const [newsRes, tradesRes, statsRes, analyticsRes] = await Promise.all([
        fetch(`${API}/api/news`), fetch(`${API}/api/trades`), fetch(`${API}/api/stats`), fetch(`${API}/api/analytics`),
      ]);
      if (!newsRes.ok || !tradesRes.ok || !statsRes.ok || !analyticsRes.ok) throw new Error("API error");
      const [newsData, tradesData, statsData, analyticsData] = await Promise.all([
        newsRes.json(), tradesRes.json(), statsRes.json(), analyticsRes.json(),
      ]);
      setNews(newsData); setTrades(tradesData); setStats(statsData); setAnalytics(analyticsData);
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
    if (msg.type === "bot_state" && typeof msg.last_action === "string" && msg.last_action !== "None") {
      fetchData();
    }
  }, [fetchData]);

  const wsConnected = useDashboardWS(handleWsMessage);

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
      <Dashboard3D />
      <ManualTradeModal open={tradeModalOpen} onClose={() => setTradeModalOpen(false)} onRefresh={fetchData} />

      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>

        {/* ── Page Header ─────────────────────────────────────────────── */}
        <div className="page-enter" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "4px" }}>
              <h1 style={{ fontFamily: "var(--font-syne)", fontSize: "28px", fontWeight: 800, letterSpacing: "-0.03em", color: "var(--text-primary)", margin: 0 }}>
                Live Dashboard
              </h1>
              {/* WS status pill */}
              <div style={{
                display: "flex", alignItems: "center", gap: "5px",
                padding: "3px 10px", borderRadius: "20px",
                background: wsConnected ? "var(--green-dim)" : "var(--amber-dim)",
                border: `1px solid ${wsConnected ? "rgba(34,197,94,0.25)" : "rgba(245,158,11,0.25)"}`,
                fontFamily: "var(--font-jetbrains)", fontSize: "9px", fontWeight: 700,
                letterSpacing: "0.12em", textTransform: "uppercase",
                color: wsConnected ? "var(--green)" : "var(--amber)"
              }}>
                <span style={{ width: "5px", height: "5px", borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
                {wsConnected ? "WS LIVE" : "RECONNECTING"}
              </div>
            </div>
            <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)", margin: 0, letterSpacing: "0.05em" }}>
              {lastRefresh && hasMounted ? `SYNCED · ${timeAgo(lastRefresh.toISOString())}` : "CONNECTING TO SYSTEMS…"}
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            {/* Refresh button */}
            <button
              onClick={fetchData} disabled={loading}
              style={{
                display: "flex", alignItems: "center", gap: "6px",
                padding: "7px 14px", borderRadius: "8px",
                background: "var(--bg-card)", border: "1px solid var(--border)",
                fontFamily: "var(--font-jetbrains)", fontSize: "11px", letterSpacing: "0.08em",
                color: loading ? "var(--text-muted)" : "var(--text-secondary)",
                textTransform: "uppercase", opacity: loading ? 0.6 : 1
              }}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ animation: loading ? "spin 1s linear infinite" : "none" }}>
                <path d="M1 6a5 5 0 1 0 5-5" strokeLinecap="round" />
                <path d="M1 2v4h4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {loading ? "SYNCING" : "REFRESH"}
            </button>
            {/* Reset Test button */}
            <button
              onClick={resetPaperTest} disabled={resetting}
              title="Wipe all trades and logs — start fresh at $10,000"
              style={{
                display: "flex", alignItems: "center", gap: "6px",
                padding: "7px 14px", borderRadius: "8px",
                background: "rgba(239,68,68,0.07)", border: "1px solid rgba(239,68,68,0.2)",
                fontFamily: "var(--font-jetbrains)", fontSize: "11px", letterSpacing: "0.08em",
                color: "var(--red)", textTransform: "uppercase", opacity: resetting ? 0.6 : 1,
                cursor: "pointer"
              }}
            >
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 2l7 7M9 2l-7 7" strokeLinecap="round" />
              </svg>
              {resetting ? "CLEARING…" : "RESET TEST"}
            </button>
          </div>
        </div>

        {/* Reset feedback banner */}
        {resetMsg && (
          <div style={{
            display: "flex", alignItems: "center", gap: "10px",
            padding: "10px 16px", borderRadius: "8px",
            background: resetMsg.ok ? "var(--green-dim)" : "var(--red-dim)",
            border: `1px solid ${resetMsg.ok ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`,
            fontFamily: "var(--font-jetbrains)", fontSize: "11px",
            color: resetMsg.ok ? "var(--green)" : "var(--red)"
          }}>
            {resetMsg.ok ? "✓" : "✗"} {resetMsg.text}
          </div>
        )}

        {/* ── Error banner ─────────────────────────────────────────────── */}
        {error && (
          <div style={{
            display: "flex", alignItems: "center", gap: "10px",
            padding: "12px 16px", borderRadius: "10px",
            background: "var(--red-dim)", border: "1px solid rgba(239,68,68,0.25)",
            fontFamily: "var(--font-jetbrains)", fontSize: "12px", color: "var(--red)"
          }}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M7 0a7 7 0 1 0 0 14A7 7 0 0 0 7 0zm0 10a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm0-7a1 1 0 0 1 1 1v4a1 1 0 0 1-2 0V4a1 1 0 0 1 1-1z" /></svg>
            {error}
          </div>
        )}

        {/* ── Stat Cards ─────────────────────────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "16px" }}>
          <StatCard
            label="Portfolio Balance"
            value={`$${stats.total_balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
            rawValue={stats.total_balance}
            animate
            sub="Available USDT · Paper Mode"
            accentColor="var(--cyan)"
            icon={<DollarSign size={14} />}
          />
          <StatCard
            label="Investment Overview"
            value={`$${stats.total_invested.toLocaleString()}`}
            sub={`${stats.active_leverage} pos · ${stats.avg_leverage.toFixed(1)}x avg lev`}
            accentColor="var(--violet)"
            icon={<Activity size={14} />}
          />
          <StatCard
            label="Realized PnL"
            value={`${stats.pnl_24h >= 0 ? "+" : ""}$${stats.pnl_24h.toFixed(2)}`}
            sub={`${stats.total_trades} closed trades total`}
            accentColor={stats.pnl_24h >= 0 ? "var(--green)" : "var(--red)"}
            icon={stats.pnl_24h >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
          />
          <StatCard
            label="AI Processing Costs"
            value={`$${stats.burn_rate.toFixed(2)}`}
            rawValue={stats.burn_rate}
            animate
            sub={`Opus · ${stats.tokens_consumed.toLocaleString()} tkns · ${stats.api_calls} calls`}
            accentColor="var(--amber)"
            icon={<Cpu size={14} />}
          />
          <StatCard
            label="Signal Health"
            value={error ? "OFFLINE" : stats.system_health}
            sub={error ? "Backend unreachable" : `${stats.signals_processed} signals processed`}
            accentColor={error ? "var(--red)" : "var(--green)"}
            icon={<Zap size={14} />}
            pulse={!error}
          />
          <StatCard
            label="Open Positions"
            value={String(openPositions.length)}
            rawValue={openPositions.length}
            animate
            sub={`Scan interval · 15 min`}
            accentColor="var(--amber)"
            icon={<Shield size={14} />}
          />
        </div>

        {/* ── AI Engine Status ──────────────────────────────────────────── */}
        {botState && (
          <div className="page-enter page-enter-delay-1" style={{
            background: "var(--bg-card)", border: "1px solid rgba(0,212,255,0.15)",
            borderRadius: "12px", padding: "16px 20px",
            boxShadow: "0 0 40px rgba(0,212,255,0.06)"
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "16px", width: "100%" }}>
              {/* Bot icon */}
              <div style={{
                width: "42px", height: "42px", borderRadius: "10px", flexShrink: 0,
                background: "rgba(0,212,255,0.08)", border: "1px solid rgba(0,212,255,0.2)",
                display: "flex", alignItems: "center", justifyContent: "center"
              }}>
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" style={{ color: "var(--cyan)" }}>
                  <rect x="3" y="6" width="14" height="10" rx="3" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M7 10h2m4 0h-2m-2 0v0" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  <path d="M10 6V4m-3 2V3m6 3V3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                </svg>
              </div>
              {/* Status text */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "2px" }}>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", fontWeight: 700, letterSpacing: "0.18em", color: "var(--cyan)", textTransform: "uppercase" }}>AI Engine</span>
                  <span className="pulse-dot cyan animate-pulse" style={{ width: "6px", height: "6px" }} />
                </div>
                <p style={{ fontFamily: "var(--font-syne)", fontSize: "14px", fontWeight: 600, color: "var(--text-primary)", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {botState.status}
                </p>
              </div>
              {/* Right side: last action + uptime */}
              <div style={{ flexShrink: 0, textAlign: "right", borderLeft: "1px solid var(--border)", paddingLeft: "16px", display: "none" }} className="sm:block">
                <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: "3px" }}>Last Action</p>
                <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "12px", color: "var(--text-secondary)", maxWidth: "220px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", margin: 0 }}>
                  {botState.last_action}
                </p>
                <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)", marginTop: "3px" }}>
                  UPTIME {hasMounted ? uptime : "—"}
                </p>
              </div>
            </div>

            {/* AI Learning Progress Bars */}
            <div style={{ marginTop: "16px", borderTop: "1px solid rgba(0,212,255,0.1)", paddingTop: "16px", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "24px" }}>
              {/* Progress bar 1: Confidence */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Avg Analysis Confidence</span>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--cyan)", fontWeight: 700 }}>{stats.ai_efficiency.toFixed(1)}%</span>
                </div>
                <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.05)", borderRadius: "2px", overflow: "hidden" }}>
                  <div style={{ width: `${stats.ai_efficiency}%`, height: "100%", background: "var(--cyan)", boxShadow: "0 0 10px var(--cyan)", transition: "width 1s ease" }} />
                </div>
              </div>
              {/* Progress bar 2: Monitoring */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Global Market Sensors</span>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--green)", fontWeight: 700 }}>Active</span>
                </div>
                <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.05)", borderRadius: "2px", overflow: "hidden" }}>
                  <div className="animate-pulse" style={{ width: "100%", height: "100%", background: "var(--green)", boxShadow: "0 0 10px var(--green)" }} />
                </div>
              </div>
              {/* Progress bar 3: Adaptation */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--text-muted)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Strategy Adaptation</span>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "9px", color: "var(--amber)", fontWeight: 700 }}>Optimizing</span>
                </div>
                <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.05)", borderRadius: "2px", overflow: "hidden" }}>
                  <div style={{ width: "75%", height: "100%", background: "var(--amber)", boxShadow: "0 0 10px var(--amber)", transition: "width 1s ease" }} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Analytics & Copilot ────────────────────────────────────────── */}
        <div className="page-enter page-enter-delay-2" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "16px" }}>

          {/* Trend & Risk Card */}
          <div className="glass-card" style={{ padding: "20px", display: "flex", flexDirection: "column", gap: "20px" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
                <Activity size={14} style={{ color: "var(--cyan)" }} />
                <span className="section-label">Trend Analysis</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                <TrendBar label="4H" timeframe="4H TREND" trend="up" />
                <TrendBar label="1H" timeframe="1H TREND" trend="flat" />
                <TrendBar label="15M" timeframe="15M TREND" trend="down" />
              </div>
            </div>

            <div style={{ borderTop: "1px solid var(--border)", paddingTop: "20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
                <Target size={14} style={{ color: "var(--amber)" }} />
                <span className="section-label">Risk Radar</span>
              </div>
              <RiskRadarGauge currentPrice={96450.25} sl={94000} tp={102000} />
            </div>
          </div>

          {/* Copilot Interface */}
          <CopilotInterface />

          {/* PnL History Card */}
          <div className="glass-card" style={{ padding: "20px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
              <Calendar size={14} style={{ color: "var(--violet)" }} />
              <span className="section-label">PnL Consistency</span>
            </div>
            <PnLCalendar analytics={analytics} />
            <div style={{ marginTop: "16px", display: "flex", gap: "12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <div style={{ width: "8px", height: "8px", background: "var(--green)", borderRadius: "1px" }} />
                <span style={{ fontSize: "9px", color: "var(--text-muted)" }}>WIN</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <div style={{ width: "8px", height: "8px", background: "var(--red)", borderRadius: "1px" }} />
                <span style={{ fontSize: "9px", color: "var(--text-muted)" }}>LOSS</span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Dashboard Grid: Live Chart + Analytics Sidebar ───────────────── */}
        <div className="page-enter page-enter-delay-2" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(400px, 1fr))", gap: "16px" }}>

          {/* TradingView Live Chart */}
          <div className="glass-card" style={{
            borderRadius: "12px", overflow: "hidden", minHeight: "460px",
            display: "flex", flexDirection: "column"
          }}>
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "12px 16px", borderBottom: "1px solid var(--border)"
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span className="pulse-dot cyan animate-pulse" style={{ width: "8px", height: "8px" }} />
                <span style={{ fontFamily: "var(--font-syne)", fontSize: "14px", fontWeight: 700, color: "var(--text-primary)" }}>BTC/USDT</span>
                <span style={{
                  fontFamily: "var(--font-jetbrains)", fontSize: "9px", padding: "2px 7px",
                  borderRadius: "4px", background: "var(--bg-surface)", border: "1px solid var(--border)",
                  color: "var(--text-muted)", letterSpacing: "0.1em"
                }}>BINANCE</span>
              </div>
              <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)", letterSpacing: "0.08em" }}>REAL-TIME · 1H</span>
            </div>
            <div style={{ flex: 1, width: "100%" }}>
              <LiveChart trades={trades} />
            </div>
          </div>

          {/* Analytics Sidebar stack */}
          <div style={{ display: "flex", flexDirection: "column", gap: "16px", minWidth: "300px" }}>
            {/* Equity Curve */}
            <div className="glass-card" style={{
              flex: 1, padding: "16px", display: "flex", flexDirection: "column"
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px" }}>
                <span style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)" }}>Portfolio Growth</span>
                <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: stats.pnl_24h >= 0 ? "var(--green)" : "var(--red)" }}>
                  {stats.pnl_24h >= 0 ? "+" : ""}{((stats.pnl_24h / 10000) * 100).toFixed(2)}%
                </span>
              </div>
              <div style={{ flex: 1, minHeight: "150px" }}>
                <PortfolioChart currentBalance={stats.total_balance} equityCurve={analytics.equity_curve} />
              </div>
            </div>

            {/* Win Rate Donut */}
            <div className="glass-card" style={{
              flex: 1, padding: "16px", display: "flex", flexDirection: "column"
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "16px" }}>
                <span style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)" }}>System Win Rate</span>
                <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)" }}>{stats.total_trades} EXECUTIONS</span>
              </div>
              <div style={{ flex: 1, minHeight: "150px" }}>
                <WinRateChart totalTrades={analytics.total_trades} winRate={analytics.win_rate} />
              </div>
            </div>
          </div>

        </div>

        {/* ── Bottom 2-col grid ─────────────────────────────────────────── */}
        <div className="page-enter page-enter-delay-3" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>

          {/* News Signals */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "12px", overflow: "hidden", display: "flex", flexDirection: "column" }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <svg width="13" height="13" viewBox="0 0 13 13" fill="currentColor" style={{ color: "var(--cyan)" }}>
                  <path d="M1 2a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V2zm2 1v2h7V3H3zm0 4v1h7V7H3zm0 3v1h4v-1H3z" />
                </svg>
                <span style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)" }}>News Signals</span>
                <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)" }}>{news.length} records</span>
              </div>
              <select
                value={visibleNews}
                onChange={(e) => setVisibleNews(Number(e.target.value))}
                style={{ padding: "3px 8px", fontSize: "11px", letterSpacing: "0.05em" }}
              >
                <option value={6}>Show 6</option>
                <option value={12}>Show 12</option>
                <option value={30}>Show 30</option>
              </select>
            </div>

            {/* Body */}
            {loading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                {[...Array(4)].map((_, i) => (
                  <div key={i} style={{ display: "flex", gap: "12px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                    <div className="shimmer" style={{ width: "38px", height: "38px", borderRadius: "8px", flexShrink: 0 }} />
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
                      <div className="shimmer" style={{ height: "12px", borderRadius: "4px", width: "80%" }} />
                      <div className="shimmer" style={{ height: "12px", borderRadius: "4px", width: "50%" }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : news.length === 0 ? (
              <div style={{ padding: "40px 16px", textAlign: "center", fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)", letterSpacing: "0.08em" }}>
                NO SIGNALS YET
              </div>
            ) : (
              <>
                <ul style={{ listStyle: "none", margin: 0, padding: 0, flex: 1 }}>
                  {news.slice(0, visibleNews).map((s) => (
                    <li key={s.id} style={{
                      display: "flex", gap: "12px", padding: "12px 16px",
                      borderBottom: "1px solid rgba(255,255,255,0.04)",
                      transition: "background 0.15s ease",
                    }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(0,212,255,0.02)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                    >
                      {/* Ticker badge */}
                      <div style={{
                        width: "38px", height: "38px", borderRadius: "8px", flexShrink: 0,
                        background: "var(--bg-surface)", border: "1px solid var(--border)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontFamily: "var(--font-jetbrains)", fontSize: "10px", fontWeight: 700,
                        color: "var(--cyan)", letterSpacing: "0.05em"
                      }}>
                        {s.ticker ?? "?"}
                      </div>
                      {/* Content */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontFamily: "var(--font-ui)", fontSize: "12px", color: "var(--text-secondary)", margin: "0 0 5px", lineHeight: 1.4, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                          {s.raw_text}
                        </p>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          {/* Score badge */}
                          {s.sentiment_score !== null && (
                            <span style={{
                              fontFamily: "var(--font-jetbrains)", fontSize: "10px", fontWeight: 700,
                              padding: "1px 6px", borderRadius: "4px",
                              background: s.sentiment_score > 0 ? "var(--green-dim)" : s.sentiment_score < 0 ? "var(--red-dim)" : "var(--amber-dim)",
                              color: getSentimentColor(s.sentiment_score),
                              border: `1px solid ${s.sentiment_score > 0 ? "rgba(34,197,94,0.2)" : s.sentiment_score < 0 ? "rgba(239,68,68,0.2)" : "rgba(245,158,11,0.2)"}`,
                            }}>
                              {s.sentiment_score > 0 ? "+" : ""}{s.sentiment_score.toFixed(2)}
                            </span>
                          )}
                          {s.confidence !== null && (
                            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)" }}>{s.confidence}% conf</span>
                          )}
                          <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)", marginLeft: "auto" }}>{timeAgo(s.created_at)}</span>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
                {visibleNews < news.length && (
                  <div style={{ padding: "10px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "center" }}>
                    <button
                      onClick={() => setVisibleNews((p) => p + 6)}
                      style={{
                        padding: "5px 14px", borderRadius: "6px",
                        background: "var(--bg-surface)", border: "1px solid var(--border)",
                        fontFamily: "var(--font-jetbrains)", fontSize: "10px", letterSpacing: "0.1em",
                        color: "var(--text-muted)", textTransform: "uppercase"
                      }}
                    >
                      Load {Math.min(6, news.length - visibleNews)} More
                    </button>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Open Positions */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "12px", overflow: "hidden", display: "flex", flexDirection: "column" }}>
            {/* Header */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: "var(--green)" }}>
                  <polyline points="1,9 4,5 7,7 10,2 12,4" /><path d="M12 2h-3m3 0v3" />
                </svg>
                <span style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)" }}>Open Positions</span>
                <span style={{
                  fontFamily: "var(--font-jetbrains)", fontSize: "10px", padding: "1px 7px", borderRadius: "4px",
                  background: openPositions.length > 0 ? "var(--green-dim)" : "var(--bg-surface)",
                  border: `1px solid ${openPositions.length > 0 ? "rgba(34,197,94,0.25)" : "var(--border)"}`,
                  color: openPositions.length > 0 ? "var(--green)" : "var(--text-muted)"
                }}>
                  {openPositions.length} ACTIVE
                </span>
              </div>
            </div>

            {/* Table */}
            <div style={{ overflowX: "auto", flex: 1 }}>
              <table>
                <thead>
                  <tr>
                    {["Ticker", "Entry", "Size", "Status"].map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {openPositions.slice(0, visiblePositions).map((t) => (
                    <tr key={t.id}>
                      <td style={{ fontFamily: "var(--font-jetbrains)", fontWeight: 700, color: "var(--cyan)" }}>{t.ticker}</td>
                      <td style={{ color: "var(--text-primary)" }}>{formatPrice(t.price)}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{Number(t.amount).toFixed(4)}</td>
                      <td>
                        <span style={{ display: "flex", alignItems: "center", gap: "5px" }}>
                          <span className="pulse-dot green" style={{ width: "6px", height: "6px" }} />
                          <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--green)" }}>HOLDING</span>
                        </span>
                      </td>
                    </tr>
                  ))}
                  {openPositions.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: "center", fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)", letterSpacing: "0.08em", padding: "32px 16px" }}>
                        NO OPEN POSITIONS
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {visiblePositions < openPositions.length && (
              <div style={{ padding: "10px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "center" }}>
                <button onClick={() => setVisiblePositions((p) => p + 5)} style={{
                  padding: "5px 14px", borderRadius: "6px", background: "var(--bg-surface)", border: "1px solid var(--border)",
                  fontFamily: "var(--font-jetbrains)", fontSize: "10px", letterSpacing: "0.1em", color: "var(--text-muted)", textTransform: "uppercase"
                }}>Load More</button>
              </div>
            )}
          </div>
        </div>

        {/* ── Trade History full-width ───────────────────────────────────── */}
        <div className="page-enter page-enter-delay-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "12px", overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ color: "var(--violet)" }}>
                <circle cx="6.5" cy="6.5" r="5.5" /><polyline points="6.5,3.5 6.5,6.5 8.5,8.5" />
              </svg>
              <span style={{ fontFamily: "var(--font-syne)", fontSize: "13px", fontWeight: 700, color: "var(--text-primary)" }}>Trade History</span>
            </div>
            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)" }}>{tradeHistory.length} records</span>
          </div>
          <div style={{ overflowX: "auto" }}>
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
                    <td style={{ fontFamily: "var(--font-jetbrains)", fontWeight: 700, color: "var(--text-primary)" }}>{t.ticker}</td>
                    <td>
                      <span style={{
                        fontFamily: "var(--font-jetbrains)", fontSize: "10px", fontWeight: 700,
                        padding: "2px 7px", borderRadius: "4px",
                        background: t.action.toUpperCase() === "BUY" ? "var(--green-dim)" : "var(--red-dim)",
                        color: t.action.toUpperCase() === "BUY" ? "var(--green)" : "var(--red)",
                        border: `1px solid ${t.action.toUpperCase() === "BUY" ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)"}`,
                      }}>
                        {t.action.toUpperCase() === "BUY" ? "▲ LONG" : "▼ SHORT"}
                      </span>
                    </td>
                    <td>{Number(t.amount).toFixed(4)}</td>
                    <td style={{ color: "var(--text-primary)" }}>{formatPrice(t.price)}</td>
                    <td style={{ color: "var(--text-muted)" }}>{timeAgo(t.created_at)}</td>
                    <td>
                      <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)" }}>✔ CLOSED</span>
                    </td>
                  </tr>
                ))}
                {tradeHistory.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", fontFamily: "var(--font-jetbrains)", fontSize: "11px", color: "var(--text-muted)", letterSpacing: "0.08em", padding: "32px 16px" }}>
                      NO TRADE HISTORY
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ── Floating Action Button ─────────────────────────────────────── */}
      <button
        id="manual-trade-btn"
        onClick={() => setTradeModalOpen(true)}
        style={{
          position: "fixed", bottom: "24px", right: "24px", zIndex: 40,
          display: "flex", alignItems: "center", gap: "8px",
          padding: "12px 20px", borderRadius: "40px",
          background: "linear-gradient(135deg, #00d4ff 0%, #0066cc 100%)",
          border: "none", color: "white",
          fontFamily: "var(--font-jetbrains)", fontSize: "12px", fontWeight: 700,
          letterSpacing: "0.1em", textTransform: "uppercase",
          boxShadow: "0 0 30px rgba(0,212,255,0.35), 0 8px 24px rgba(0,0,0,0.5)",
          cursor: "pointer"
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
        @media (max-width: 768px) {
          .sm\\:block { display: block !important; }
        }
      `}</style>
    </>
  );
}
