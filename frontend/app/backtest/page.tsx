"use client";

import { useState } from "react";
import BacktestChart from "@/components/BacktestChart";
import MonteCarloChart from "@/components/MonteCarloChart";
import StressTestChart from "@/components/StressTestChart";
import { 
  TrendingUp, 
  Dices, 
  Flame, 
  Sliders, 
  Play, 
  Percent, 
  Activity, 
  DollarSign, 
  ShieldAlert, 
  BarChart4, 
  Clock, 
  PieChart as PieIcon, 
  CheckSquare, 
  Square 
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from "recharts";

interface BacktestResult {
  metrics: {
    final_balance: number;
    total_return_pct: number;
    total_trades: number;
    win_rate_pct: number;
    avg_win_pct: number;
    avg_loss_pct: number;
    max_drawdown_pct: number;
  };
  equity_curve: { time: number; value: number }[];
  trades: any[];
}

interface MonteCarloResult {
  metrics: {
    n_simulations: number;
    trades_per_sim: number;
    mean_balance: number;
    std_balance: number;
    p5_balance: number;
    p25_balance: number;
    median_balance: number;
    p75_balance: number;
    p95_balance: number;
    dd_mean: number;
    dd_95: number;
    dd_max: number;
    ruin_count: number;
    risk_of_ruin: number;
    prob_profit: number;
    median_return: number;
  };
  input_distribution: {
    n_trades: number;
    mean_pnl: number;
    std_pnl: number;
    min_pnl: number;
    max_pnl: number;
    win_rate: number;
  };
  sample_curves: number[][];
  histogram: { bucket: string; count: number }[];
  verdict: string;
}

interface StressTestResult {
  per_ticker: {
    symbol: string;
    initial_balance: number;
    final_balance: number;
    total_return_pct: number;
    total_trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    max_drawdown_pct: number;
    sharpe_ratio: number;
    exit_reasons: Record<string, number>;
    equity_curve: { timestamp: string; equity: number }[];
    trades: any[];
  }[];
  portfolio_summary: {
    total_initial: number;
    total_final: number;
    pnl_usd: number;
    pnl_pct: number;
    total_trades: number;
    win_rate: number;
    total_fees: number;
    avg_drawdown_pct: number;
    avg_sharpe: number;
    best_ticker: string;
    worst_ticker: string;
  };
  exit_reasons_total: Record<string, number>;
}

const parseNumber = (val: any): number => {
  if (typeof val === "number") return val;
  if (!val) return 0;
  const clean = String(val).replace(",", ".");
  const parsed = parseFloat(clean);
  return isNaN(parsed) ? 0 : parsed;
};

export default function BacktestPage() {
  const [activeTab, setActiveTab] = useState<"strategy" | "monte_carlo" | "stress">("strategy");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // 1. Вкладка Strategy Backtest
  const [strategyResult, setStrategyResult] = useState<BacktestResult | null>(null);
  const [strategyParams, setStrategyParams] = useState({
    symbol: "BTC/USDT",
    timeframe: "1h",
    days_back: "90",
    initial_balance: "1000.0",
    hard_stop: "0.97",
    trailing_activation: "1.05",
    take_profit: "1.10",
    trailing_distance: "0.985"
  });

  // 2. Вкладка Monte Carlo
  const [mcResult, setMcResult] = useState<MonteCarloResult | null>(null);
  const [mcParams, setMcParams] = useState({
    n_simulations: "10000",
    trades_per_sim: "200",
    initial_balance: "10000.0"
  });

  // 3. Вкладка Stress Test
  const [stressResult, setStressResult] = useState<StressTestResult | null>(null);
  const [stressTickers, setStressTickers] = useState<Record<string, boolean>>({
    "BTC/USDT": true,
    "ETH/USDT": true,
    "SOL/USDT": true,
    "DOGE/USDT": false,
    "XRP/USDT": false
  });
  const [stressParams, setStressParams] = useState({
    days_back: "365",
    initial_balance: "10000.0"
  });

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    
    if (activeTab === "strategy") {
      setStrategyParams(prev => ({ 
        ...prev, 
        [name]: value 
      }));
    } else if (activeTab === "monte_carlo") {
      setMcParams(prev => ({ 
        ...prev, 
        [name]: value 
      }));
    } else {
      setStressParams(prev => ({
        ...prev,
        [name]: value
      }));
    }
  };

  const toggleStressTicker = (ticker: string) => {
    setStressTickers(prev => ({ ...prev, [ticker]: !prev[ticker] }));
  };

  const runStrategyBacktest = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setStrategyResult(null);

    const payload = {
      symbol: strategyParams.symbol,
      timeframe: strategyParams.timeframe,
      days_back: parseNumber(strategyParams.days_back),
      initial_balance: parseNumber(strategyParams.initial_balance),
      hard_stop: parseNumber(strategyParams.hard_stop),
      trailing_activation: parseNumber(strategyParams.trailing_activation),
      take_profit: parseNumber(strategyParams.take_profit),
      trailing_distance: parseNumber(strategyParams.trailing_distance)
    };

    try {
      const res = await fetch("http://localhost:8000/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status === "success") {
        setStrategyResult(data.data);
      } else {
        setError(data.message || "Ошибка запуска бэктеста.");
      }
    } catch (err: any) {
      setError(err.message || "Не удалось связаться с сервером бэкенда.");
    } finally {
      setLoading(false);
    }
  };

  const runMonteCarlo = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setMcResult(null);

    const payload = {
      n_simulations: parseNumber(mcParams.n_simulations),
      trades_per_sim: parseNumber(mcParams.trades_per_sim),
      initial_balance: parseNumber(mcParams.initial_balance)
    };

    try {
      const res = await fetch("http://localhost:8000/api/monte-carlo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status === "success") {
        setMcResult(data.data);
      } else {
        setError(data.message || "Ошибка запуска симуляции Монте-Карло.");
      }
    } catch (err: any) {
      setError(err.message || "Не удалось связаться с сервером бэкенда.");
    } finally {
      setLoading(false);
    }
  };

  const runStressTest = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setStressResult(null);

    const activeList = Object.keys(stressTickers).filter(t => stressTickers[t]);
    if (activeList.length === 0) {
      setError("Выберите хотя бы один тикер для стресс-теста.");
      setLoading(false);
      return;
    }

    const payload = {
      tickers: activeList,
      days_back: parseNumber(stressParams.days_back),
      initial_balance: parseNumber(stressParams.initial_balance)
    };

    try {
      const res = await fetch("http://localhost:8000/api/stress-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status === "success") {
        setStressResult(data.data);
      } else {
        setError(data.message || "Ошибка запуска стресс-теста.");
      }
    } catch (err: any) {
      setError(err.message || "Не удалось связаться с сервером бэкенда.");
    } finally {
      setLoading(false);
    }
  };

  // Цвета для Recharts Pie
  const COLORS = ["#10b981", "#f43f5e", "#f59e0b", "#3b82f6", "#a855f7"];

  return (
    <div className="space-y-6 page-enter">
      {/* ── Page Header ── */}
      <header className="mb-4">
        <h1 className="text-3xl font-extrabold tracking-tight text-[var(--text-primary)]">
          🧪 Visual Backtesting Laboratory
        </h1>
        <p className="text-sm text-[var(--text-secondary)] font-mono mt-1">
          Verify and stress-test risk profiles using institutional-grade quantitative engines.
        </p>
      </header>

      {/* ── Tabs Navigation ── */}
      <div className="flex border-b border-[var(--border)] gap-2">
        <button
          onClick={() => { setActiveTab("strategy"); setError(""); }}
          className={`flex items-center gap-2 px-4 py-3 border-b-2 font-medium text-sm transition-all ${
            activeTab === "strategy"
              ? "border-[var(--green)] text-[var(--text-primary)] bg-[var(--bg-hover)]"
              : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          <TrendingUp size={16} />
          Strategy Backtest
        </button>
        <button
          onClick={() => { setActiveTab("monte_carlo"); setError(""); }}
          className={`flex items-center gap-2 px-4 py-3 border-b-2 font-medium text-sm transition-all ${
            activeTab === "monte_carlo"
              ? "border-[var(--green)] text-[var(--text-primary)] bg-[var(--bg-hover)]"
              : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          <Dices size={16} />
          Monte Carlo Sim
        </button>
        <button
          onClick={() => { setActiveTab("stress"); setError(""); }}
          className={`flex items-center gap-2 px-4 py-3 border-b-2 font-medium text-sm transition-all ${
            activeTab === "stress"
              ? "border-[var(--green)] text-[var(--text-primary)] bg-[var(--bg-hover)]"
              : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          }`}
        >
          <Flame size={16} />
          3-Year Stress Test
        </button>
      </div>

      {error && (
        <div className="p-4 bg-[var(--red-dim)] border border-[var(--red)] rounded-xl text-sm text-[var(--red)] font-mono flex items-center gap-2">
          <ShieldAlert size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* ── TAB CONTENT ── */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        
        {/* ========================================== */}
        {/* ── SIDEBAR CONFIGURATION PANEL ── */}
        {/* ========================================== */}
        <div className="lg:col-span-1 p-5 rounded-xl card bg-[var(--bg-card)]">
          <h3 className="text-md font-bold mb-4 flex items-center gap-2 text-[var(--text-primary)]">
            <Sliders size={18} className="text-[var(--green)]" />
            Parameters
          </h3>

          {/* ── Strategy Tab Form ── */}
          {activeTab === "strategy" && (
            <form onSubmit={runStrategyBacktest} className="space-y-4">
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Symbol</label>
                <select name="symbol" value={strategyParams.symbol} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm">
                  <option value="BTC/USDT">BTC/USDT</option>
                  <option value="ETH/USDT">ETH/USDT</option>
                  <option value="SOL/USDT">SOL/USDT</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Timeframe</label>
                <select name="timeframe" value={strategyParams.timeframe} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm">
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="4h">4h</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Days Back</label>
                <input type="text" inputMode="numeric" pattern="[0-9]*" name="days_back" value={strategyParams.days_back} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Stop Loss (0.97 = -3%)</label>
                <input type="text" inputMode="decimal" name="hard_stop" value={strategyParams.hard_stop} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Take Profit (1.10 = +10%)</label>
                <input type="text" inputMode="decimal" name="take_profit" value={strategyParams.take_profit} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Trail Activation (1.05 = +5%)</label>
                <input type="text" inputMode="decimal" name="trailing_activation" value={strategyParams.trailing_activation} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              
              <button
                type="submit"
                disabled={loading}
                className={`w-full py-3 mt-4 rounded-lg font-bold text-sm tracking-wide transition-all flex items-center justify-center gap-2 ${
                  loading
                    ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
                    : "bg-[var(--green)] hover:bg-[#0fa572] text-[var(--bg-base)] shadow-md"
                }`}
              >
                {loading ? "Simulating..." : (
                  <>
                    <Play size={14} fill="currentColor" />
                    RUN BACKTEST
                  </>
                )}
              </button>
            </form>
          )}

          {/* ── Monte Carlo Tab Form ── */}
          {activeTab === "monte_carlo" && (
            <form onSubmit={runMonteCarlo} className="space-y-4">
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Simulations</label>
                <input type="text" inputMode="numeric" pattern="[0-9]*" name="n_simulations" value={mcParams.n_simulations} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Trades Per Sim</label>
                <input type="text" inputMode="numeric" pattern="[0-9]*" name="trades_per_sim" value={mcParams.trades_per_sim} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Initial Capital ($)</label>
                <input type="text" inputMode="decimal" name="initial_balance" value={mcParams.initial_balance} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>

              <button
                type="submit"
                disabled={loading}
                className={`w-full py-3 mt-4 rounded-lg font-bold text-sm tracking-wide transition-all flex items-center justify-center gap-2 ${
                  loading
                    ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
                    : "bg-[var(--green)] hover:bg-[#0fa572] text-[var(--bg-base)] shadow-md"
                }`}
              >
                {loading ? "Computing 10k Paths..." : (
                  <>
                    <Play size={14} fill="currentColor" />
                    RUN SIMULATIONS
                  </>
                )}
              </button>
            </form>
          )}

          {/* ── Stress Test Tab Form ── */}
          {activeTab === "stress" && (
            <form onSubmit={runStressTest} className="space-y-4">
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-2 font-mono uppercase tracking-wider">Select Tickers</label>
                <div className="space-y-2">
                  {Object.keys(stressTickers).map(ticker => (
                    <div
                      key={ticker}
                      onClick={() => toggleStressTicker(ticker)}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--bg-hover)] border border-[var(--border)] cursor-pointer hover:border-[var(--border-hover)] transition-all select-none"
                    >
                      {stressTickers[ticker] ? (
                        <CheckSquare size={16} className="text-[var(--green)]" />
                      ) : (
                        <Square size={16} className="text-[var(--text-muted)]" />
                      )}
                      <span className="font-mono text-sm text-[var(--text-primary)]">{ticker}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Days Back (Max 1095)</label>
                <input type="text" inputMode="numeric" pattern="[0-9]*" name="days_back" value={stressParams.days_back} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="block text-xs text-[var(--text-secondary)] mb-1 font-mono uppercase tracking-wider">Capital per Ticker ($)</label>
                <input type="text" inputMode="decimal" name="initial_balance" value={stressParams.initial_balance} onChange={handleInputChange} className="w-full bg-[var(--bg-input)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>

              <button
                type="submit"
                disabled={loading}
                className={`w-full py-3 mt-4 rounded-lg font-bold text-sm tracking-wide transition-all flex items-center justify-center gap-2 ${
                  loading
                    ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
                    : "bg-[var(--green)] hover:bg-[#0fa572] text-[var(--bg-base)] shadow-md"
                }`}
              >
                {loading ? "Running Stress Engine..." : (
                  <>
                    <Flame size={14} fill="currentColor" />
                    RUN STRESS TEST
                  </>
                )}
              </button>
            </form>
          )}
        </div>

        {/* ========================================== */}
        {/* ── RESULTS DISPLAY PANEL ── */}
        {/* ========================================== */}
        <div className="lg:col-span-3 space-y-6">

          {/* ── STATE 1: STRATEGY TAB RESULTS ── */}
          {activeTab === "strategy" && (
            <>
              {loading && (
                <div className="min-h-[400px] flex flex-col items-center justify-center border border-[var(--border)] bg-[var(--bg-card)] rounded-xl relative">
                  <Activity className="text-[var(--green)] animate-pulse mb-3" size={32} />
                  <span className="font-mono text-sm text-[var(--text-primary)]">Executing historical strategy backtest...</span>
                  <span className="font-mono text-xs text-[var(--text-muted)] mt-1">Downloading candles from Binance cache.</span>
                </div>
              )}

              {!strategyResult && !loading && (
                <div className="min-h-[400px] flex flex-col items-center justify-center border border-[var(--border)] bg-[var(--bg-card)] rounded-xl relative text-center px-4">
                  <TrendingUp className="text-[var(--text-muted)] mb-3" size={32} />
                  <span className="font-mono text-sm text-[var(--text-secondary)]">Enter strategy parameters and click RUN to view results.</span>
                </div>
              )}

              {strategyResult && !loading && (
                <div className="space-y-6">
                  {/* Metrics Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Final Balance</div>
                      <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">
                        ${strategyResult.metrics.final_balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Total Return</div>
                      <div className={`text-2xl font-bold font-mono ${strategyResult.metrics.total_return_pct >= 0 ? "val-up" : "val-down"}`}>
                        {strategyResult.metrics.total_return_pct > 0 ? "+" : ""}{strategyResult.metrics.total_return_pct}%
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Win Rate</div>
                      <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">
                        {strategyResult.metrics.win_rate_pct}%
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Max Drawdown</div>
                      <div className="text-2xl font-bold font-mono val-down">
                        -{strategyResult.metrics.max_drawdown_pct}%
                      </div>
                    </div>
                  </div>

                  {/* Chart Container */}
                  <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] relative">
                    <h3 className="text-sm font-semibold mb-4 flex items-center gap-2 font-mono text-[var(--text-primary)] uppercase tracking-wider">
                      <Activity size={14} className="text-[var(--green)]" />
                      Equity Growth Curve
                    </h3>
                    <BacktestChart data={strategyResult.equity_curve} />
                  </div>

                  {/* Trade Log Table */}
                  <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
                    <div className="p-4 border-b border-[var(--border)] bg-zinc-900/30 flex justify-between items-center">
                      <h3 className="text-sm font-semibold font-mono text-[var(--text-primary)] uppercase tracking-wider">
                        Trade Records ({strategyResult.trades.length})
                      </h3>
                    </div>
                    <div className="overflow-x-auto max-h-[300px]">
                      <table>
                        <thead>
                          <tr>
                            <th>Side</th>
                            <th>Entry Time</th>
                            <th>Entry Price</th>
                            <th>PnL (%)</th>
                            <th>Reason</th>
                          </tr>
                        </thead>
                        <tbody>
                          {strategyResult.trades.length === 0 ? (
                            <tr>
                              <td colSpan={5} className="text-center text-[var(--text-muted)]">No trades executed in this period.</td>
                            </tr>
                          ) : (
                            strategyResult.trades.map((t, idx) => (
                              <tr key={idx}>
                                <td>
                                  <span className={`badge ${t.side === "LONG" ? "badge-green" : "badge-red"}`}>
                                    {t.side}
                                  </span>
                                </td>
                                <td>{t.timestamp || t.time}</td>
                                <td>${Number(t.entry_price || t.price).toFixed(2)}</td>
                                <td className={Number(t.pnl_pct ?? t.return_pct ?? t.pnl ?? 0) >= 0 ? "val-up" : "val-down"}>
                                  {Number(t.pnl_pct ?? t.return_pct ?? t.pnl ?? 0) > 0 ? "+" : ""}{Number(t.pnl_pct ?? t.return_pct ?? t.pnl ?? 0).toFixed(2)}%
                                </td>
                                <td>
                                  <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-secondary)]">
                                    {t.reason || "active"}
                                  </span>
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── STATE 2: MONTE CARLO TAB RESULTS ── */}
          {activeTab === "monte_carlo" && (
            <>
              {loading && (
                <div className="min-h-[400px] flex flex-col items-center justify-center border border-[var(--border)] bg-[var(--bg-card)] rounded-xl relative">
                  <Dices className="text-[var(--green)] animate-spin mb-3" size={32} />
                  <span className="font-mono text-sm text-[var(--text-primary)]">Simulating 10,000 randomized equity paths...</span>
                  <span className="font-mono text-xs text-[var(--text-muted)] mt-1">Bootstrapping from historical trades.</span>
                </div>
              )}

              {!mcResult && !loading && (
                <div className="min-h-[400px] flex flex-col items-center justify-center border border-[var(--border)] bg-[var(--bg-card)] rounded-xl relative text-center px-4">
                  <Dices className="text-[var(--text-muted)] mb-3" size={32} />
                  <span className="font-mono text-sm text-[var(--text-secondary)]">Start simulations to calculate Risk of Ruin & spaghetti probability cone.</span>
                </div>
              )}

              {mcResult && !loading && (
                <div className="space-y-6">
                  {/* Verdict Banner */}
                  <div className={`p-4 rounded-xl border flex items-center justify-between ${
                    mcResult.verdict === "CLEARED" 
                      ? "bg-[var(--green-dim)] border-[var(--green)]" 
                      : "bg-[var(--red-dim)] border-[var(--red)]"
                  }`}>
                    <div>
                      <h4 className={`text-md font-bold ${mcResult.verdict === "CLEARED" ? "text-[var(--green)]" : "text-[var(--red)]"}`}>
                        Monte Carlo Risk Analysis: {mcResult.verdict === "CLEARED" ? "CLEARED FOR LIVE" : "RISK WARNED"}
                      </h4>
                      <p className="text-xs text-[var(--text-secondary)] mt-1 font-mono">
                        {mcResult.verdict === "CLEARED" 
                          ? "Risk of Ruin is under 1%. The current parameter configuration meets institutional risk parameters."
                          : "Risk of Ruin is above 1%. Revise strategy indicators or dynamic stop-losses to decrease risk of drawdown."}
                      </p>
                    </div>
                    <span className={`px-3 py-1.5 rounded font-mono font-bold text-sm tracking-wider uppercase ${
                      mcResult.verdict === "CLEARED" 
                        ? "bg-[var(--green)] text-[var(--bg-base)]" 
                        : "bg-[var(--red)] text-white"
                    }`}>
                      {mcResult.verdict}
                    </span>
                  </div>

                  {/* MC Key Metrics */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Risk of Ruin</div>
                      <div className={`text-2xl font-bold font-mono ${mcResult.metrics.risk_of_ruin < 1.0 ? "val-up" : "val-down"}`}>
                        {mcResult.metrics.risk_of_ruin}%
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Median End Balance</div>
                      <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">
                        ${mcResult.metrics.median_balance.toLocaleString()}
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Probability of Profit</div>
                      <div className="text-2xl font-bold font-mono text-[var(--green)]">
                        {mcResult.metrics.prob_profit}%
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">95% CI drawdown</div>
                      <div className="text-2xl font-bold font-mono val-down">
                        -{mcResult.metrics.dd_95}%
                      </div>
                    </div>
                  </div>

                  {/* Spaghetti Chart */}
                  <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] relative">
                    <h3 className="text-sm font-semibold mb-4 flex items-center gap-2 font-mono text-[var(--text-primary)] uppercase tracking-wider">
                      <Dices size={14} className="text-[var(--green)]" />
                      Random-Walk Spaghetti Chart (200 Paths)
                    </h3>
                    <MonteCarloChart curves={mcResult.sample_curves} initialBalance={mcParams.initial_balance} />
                  </div>

                  {/* Histogram and Input distribution grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Input distribution metrics */}
                    <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <h3 className="text-sm font-semibold mb-4 font-mono text-[var(--text-primary)] uppercase tracking-wider">
                        Historical Trade Distribution
                      </h3>
                      <div className="space-y-3 font-mono text-sm">
                        <div className="flex justify-between py-1 border-b border-zinc-800">
                          <span className="text-[var(--text-secondary)]">Historical Trades Sampled:</span>
                          <span className="text-[var(--text-primary)]">{mcResult.input_distribution.n_trades}</span>
                        </div>
                        <div className="flex justify-between py-1 border-b border-zinc-800">
                          <span className="text-[var(--text-secondary)]">Mean PnL per Trade:</span>
                          <span className={mcResult.input_distribution.mean_pnl >= 0 ? "val-up" : "val-down"}>
                            {mcResult.input_distribution.mean_pnl >= 0 ? "+" : ""}{mcResult.input_distribution.mean_pnl}%
                          </span>
                        </div>
                        <div className="flex justify-between py-1 border-b border-zinc-800">
                          <span className="text-[var(--text-secondary)]">Standard Deviation:</span>
                          <span className="text-[var(--text-primary)]">{mcResult.input_distribution.std_pnl}%</span>
                        </div>
                        <div className="flex justify-between py-1 border-b border-zinc-800">
                          <span className="text-[var(--text-secondary)]">Sample Win Rate:</span>
                          <span className="text-[var(--text-primary)]">{mcResult.input_distribution.win_rate}%</span>
                        </div>
                        <div className="flex justify-between py-1">
                          <span className="text-[var(--text-secondary)]">Max PnL Range:</span>
                          <span className="text-[var(--text-primary)]">
                            [{mcResult.input_distribution.min_pnl}% ... {mcResult.input_distribution.max_pnl}%]
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Bar chart histogram of final balance distribution */}
                    <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <h3 className="text-sm font-semibold mb-4 font-mono text-[var(--text-primary)] uppercase tracking-wider">
                        Final Capital Distribution (Percentiles)
                      </h3>
                      <div className="h-[180px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={mcResult.histogram}>
                            <XAxis dataKey="bucket" hide />
                            <YAxis width={30} stroke="#52525b" fontSize={10} />
                            <Tooltip contentStyle={{ background: "#18181b", border: "1px solid rgba(255,255,255,0.06)" }} />
                            <Bar dataKey="count" fill="rgba(16, 185, 129, 0.4)" stroke="#10b981" radius={[3, 3, 0, 0]} />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-center text-xs mt-3 font-mono">
                        <div className="bg-zinc-900/30 py-1.5 rounded">
                          <div className="text-[var(--text-muted)] uppercase tracking-wider text-[10px]">p5 (worst)</div>
                          <div className="val-down font-bold">${mcResult.metrics.p5_balance.toLocaleString()}</div>
                        </div>
                        <div className="bg-zinc-900/30 py-1.5 rounded">
                          <div className="text-[var(--text-muted)] uppercase tracking-wider text-[10px]">p50 (median)</div>
                          <div className="text-zinc-300 font-bold">${mcResult.metrics.median_balance.toLocaleString()}</div>
                        </div>
                        <div className="bg-zinc-900/30 py-1.5 rounded">
                          <div className="text-[var(--text-muted)] uppercase tracking-wider text-[10px]">p95 (best)</div>
                          <div className="val-up font-bold">${mcResult.metrics.p95_balance.toLocaleString()}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* ── STATE 3: STRESS TEST TAB RESULTS ── */}
          {activeTab === "stress" && (
            <>
              {loading && (
                <div className="min-h-[400px] flex flex-col items-center justify-center border border-[var(--border)] bg-[var(--bg-card)] rounded-xl relative">
                  <Flame className="text-[var(--red)] animate-pulse mb-3" size={32} />
                  <span className="font-mono text-sm text-[var(--text-primary)]">Executing 3-Year comprehensive stress test...</span>
                  <span className="font-mono text-xs text-[var(--text-muted)] mt-1">Simulating long & short models with BTC Health Guard.</span>
                </div>
              )}

              {!stressResult && !loading && (
                <div className="min-h-[400px] flex flex-col items-center justify-center border border-[var(--border)] bg-[var(--bg-card)] rounded-xl relative text-center px-4">
                  <Flame className="text-[var(--text-muted)] mb-3" size={32} />
                  <span className="font-mono text-sm text-[var(--text-secondary)]">Run stress test to simulate full 3-year performance across portfolio tickers.</span>
                </div>
              )}

              {stressResult && !loading && (
                <div className="space-y-6">
                  {/* Aggregated Portfolio Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Portfolio Return</div>
                      <div className={`text-2xl font-bold font-mono ${stressResult.portfolio_summary.pnl_pct >= 0 ? "val-up" : "val-down"}`}>
                        {stressResult.portfolio_summary.pnl_pct > 0 ? "+" : ""}{stressResult.portfolio_summary.pnl_pct.toFixed(2)}%
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Portfolio Net P&L</div>
                      <div className={`text-2xl font-bold font-mono ${stressResult.portfolio_summary.pnl_usd >= 0 ? "val-up" : "val-down"}`}>
                        ${stressResult.portfolio_summary.pnl_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Aggregated Trades</div>
                      <div className="text-2xl font-bold font-mono text-[var(--text-primary)]">
                        {stressResult.portfolio_summary.total_trades}
                      </div>
                    </div>
                    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                      <div className="text-xs text-[var(--text-muted)] mb-1 font-mono uppercase tracking-wider">Avg Max Drawdown</div>
                      <div className="text-2xl font-bold font-mono val-down">
                        -{stressResult.portfolio_summary.avg_drawdown_pct}%
                      </div>
                    </div>
                  </div>

                  {/* Combined Stress Test Curves Chart */}
                  <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] relative">
                    <h3 className="text-sm font-semibold mb-4 flex items-center gap-2 font-mono text-[var(--text-primary)] uppercase tracking-wider">
                      <Flame size={14} className="text-[var(--red)]" />
                      Combined Portfolio Equity Performance
                    </h3>
                    <StressTestChart tickerResults={stressResult.per_ticker} />
                  </div>

                  {/* Breakdown Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Per Ticker Breakdown List */}
                    <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-4">
                      <h3 className="text-sm font-semibold font-mono text-[var(--text-primary)] uppercase tracking-wider">
                        Asset performance dashboard
                      </h3>
                      <div className="space-y-3">
                        {stressResult.per_ticker.map((item, idx) => (
                          <div key={idx} className="p-3 bg-zinc-900/30 border border-[var(--border)] rounded-lg flex items-center justify-between">
                            <div>
                              <div className="font-mono font-bold text-sm text-[var(--text-primary)]">{item.symbol}</div>
                              <div className="text-xs text-[var(--text-muted)] font-mono mt-0.5">{item.total_trades} trades | WR: {item.win_rate.toFixed(1)}%</div>
                            </div>
                            <div className="text-right">
                              <div className={`font-mono font-bold text-sm ${item.total_return_pct >= 0 ? "val-up" : "val-down"}`}>
                                {item.total_return_pct >= 0 ? "+" : ""}{item.total_return_pct.toFixed(2)}%
                              </div>
                              <div className="text-xs text-[var(--text-muted)] font-mono mt-0.5">DD: -{item.max_drawdown_pct}% | Sharpe: {item.sharpe_ratio}</div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Exit reasons distribution pie chart */}
                    <div className="p-5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] flex flex-col justify-between">
                      <h3 className="text-sm font-semibold font-mono text-[var(--text-primary)] uppercase tracking-wider mb-2">
                        Exit Reasons Breakdown
                      </h3>
                      <div className="flex-1 min-h-[160px] flex items-center justify-center">
                        <ResponsiveContainer width="100%" height={160}>
                          <PieChart>
                            <Pie
                              data={Object.keys(stressResult.exit_reasons_total).map(k => ({
                                name: k,
                                value: stressResult.exit_reasons_total[k]
                              }))}
                              cx="50%"
                              cy="50%"
                              innerRadius={45}
                              outerRadius={65}
                              paddingAngle={4}
                              dataKey="value"
                            >
                              {Object.keys(stressResult.exit_reasons_total).map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                              ))}
                            </Pie>
                            <Tooltip contentStyle={{ background: "#18181b", border: "1px solid rgba(255,255,255,0.06)" }} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs font-mono mt-2">
                        {Object.keys(stressResult.exit_reasons_total).map((k, index) => (
                          <div key={k} className="flex items-center gap-1.5">
                            <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                            <span className="text-[var(--text-secondary)] capitalize">{k.replace("_", " ")}:</span>
                            <span className="text-[var(--text-primary)] font-bold">{stressResult.exit_reasons_total[k]}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

        </div>
      </div>
    </div>
  );
}
