"use client";

import { useState } from "react";
import {
    Settings,
    Key,
    TrendingUp,
    ShieldCheck,
    Eye,
    EyeOff,
    Save,
    CheckCircle2,
} from "lucide-react";

function SectionCard({ title, icon: Icon, children }: {
    title: string;
    icon: React.ElementType | string;
    children: React.ReactNode;
}) {
    return (
        <div className="rounded-2xl border border-gray-800 bg-gray-900/50 backdrop-blur-sm overflow-hidden">
            <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-800/80">
                <Icon className="w-4 h-4 text-cyan-400" />
                <h2 className="text-sm font-semibold text-white">{title}</h2>
            </div>
            <div className="px-6 py-5 space-y-5">{children}</div>
        </div>
    );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
    return (
        <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">{label}</label>
            {children}
            {hint && <p className="text-[11px] text-gray-600">{hint}</p>}
        </div>
    );
}

function TextInput({ placeholder, value, onChange }: {
    placeholder?: string;
    value: string;
    onChange: (v: string) => void;
}) {
    return (
        <input
            type="text"
            placeholder={placeholder}
            value={value}
            onChange={e => onChange(e.target.value)}
            className="w-full px-4 py-2.5 rounded-xl bg-gray-800/80 border border-gray-700 text-sm text-white
                 placeholder-gray-600 focus:outline-none focus:border-cyan-500/60 focus:ring-1
                 focus:ring-cyan-500/20 transition-all"
        />
    );
}

function PasswordInput({ placeholder, value, onChange }: {
    placeholder?: string;
    value: string;
    onChange: (v: string) => void;
}) {
    const [show, setShow] = useState(false);
    return (
        <div className="relative">
            <input
                type={show ? "text" : "password"}
                placeholder={placeholder}
                value={value}
                onChange={e => onChange(e.target.value)}
                className="w-full px-4 py-2.5 pr-10 rounded-xl bg-gray-800/80 border border-gray-700 text-sm text-white
                   placeholder-gray-600 focus:outline-none focus:border-cyan-500/60 focus:ring-1
                   focus:ring-cyan-500/20 transition-all"
            />
            <button
                type="button"
                onClick={() => setShow(s => !s)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400 transition-colors"
            >
                {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
        </div>
    );
}

function NumberInput({ value, onChange, min, max, step, suffix }: {
    value: number;
    onChange: (v: number) => void;
    min?: number;
    max?: number;
    step?: number;
    suffix?: string;
}) {
    return (
        <div className="relative flex items-center">
            <input
                type="number"
                min={min}
                max={max}
                step={step ?? 0.1}
                value={value}
                onChange={e => onChange(Number(e.target.value))}
                className="w-full px-4 py-2.5 rounded-xl bg-gray-800/80 border border-gray-700 text-sm text-white
                   focus:outline-none focus:border-cyan-500/60 focus:ring-1 focus:ring-cyan-500/20
                   transition-all tabular-nums [appearance:textfield]"
            />
            {suffix && (
                <span className="absolute right-4 text-xs text-gray-500 pointer-events-none">{suffix}</span>
            )}
        </div>
    );
}

function Toggle({ enabled, onChange, label, description }: {
    enabled: boolean;
    onChange: (v: boolean) => void;
    label: string;
    description: string;
}) {
    return (
        <div className="flex items-center justify-between gap-4 py-1">
            <div>
                <p className="text-sm text-white font-medium">{label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{description}</p>
            </div>
            <button
                type="button"
                onClick={() => onChange(!enabled)}
                className={`relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent
                    transition-colors duration-200 focus:outline-none
                    ${enabled ? "bg-cyan-500" : "bg-gray-700"}`}
            >
                <span
                    className={`inline-block h-5 w-5 rounded-full bg-white shadow-lg ring-0 transition-transform duration-200
                      ${enabled ? "translate-x-5" : "translate-x-0"}`}
                />
            </button>
        </div>
    );
}

export default function SettingsPage() {
    const [saved, setSaved] = useState(false);

    // API Keys
    const [binanceKey, setBinanceKey] = useState("");
    const [binanceSecret, setBinanceSecret] = useState("");
    const [grokKey, setGrokKey] = useState("");

    // Trading Strategy
    const [dryRun, setDryRun] = useState(true);
    const [stopLoss, setStopLoss] = useState(2.5);
    const [takeProfit, setTakeProfit] = useState(5.0);

    // Risk Management
    const [maxTradeSize, setMaxTradeSize] = useState(100);

    const handleSave = () => {
        // UI-only: log and show confirmation
        console.log("Settings saved (UI only):", {
            binanceKey, binanceSecret, grokKey,
            dryRun, stopLoss, takeProfit, maxTradeSize,
        });
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
    };

    return (
        <div className="space-y-6 max-w-2xl">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
                    <Settings className="w-6 h-6 text-gray-400" />
                    Settings
                </h1>
                <p className="text-sm text-gray-500 mt-0.5">Bot configuration and trading parameters</p>
            </div>

            {/* API Keys */}
            <SectionCard title="API Keys" icon={Key}>
                <Field label="Binance API Key" hint="Your Binance read+trade API key.">
                    <PasswordInput placeholder="Enter Binance API key…" value={binanceKey} onChange={setBinanceKey} />
                </Field>
                <Field label="Binance Secret" hint="Keep this secret — never expose it publicly.">
                    <PasswordInput placeholder="Enter Binance secret…" value={binanceSecret} onChange={setBinanceSecret} />
                </Field>
                <Field label="Grok AI API Key" hint="Used by the sentiment analysis engine.">
                    <PasswordInput placeholder="Enter Grok API key…" value={grokKey} onChange={setGrokKey} />
                </Field>
            </SectionCard>

            {/* Trading Strategy */}
            <SectionCard title="Trading Strategy" icon={TrendingUp}>
                <Toggle
                    enabled={dryRun}
                    onChange={setDryRun}
                    label="Dry Run Mode"
                    description="Simulate trades without sending real orders to the exchange."
                />
                <div className="h-px bg-gray-800" />
                <Field label="Stop-Loss" hint="Automatically close a position if it drops by this percentage.">
                    <NumberInput value={stopLoss} onChange={setStopLoss} min={0.1} max={50} step={0.1} suffix="%" />
                </Field>
                <Field label="Take-Profit" hint="Automatically close a position when it gains this percentage.">
                    <NumberInput value={takeProfit} onChange={setTakeProfit} min={0.1} max={200} step={0.1} suffix="%" />
                </Field>
            </SectionCard>

            {/* Risk Management */}
            <SectionCard title="Risk Management" icon={ShieldCheck}>
                <Field
                    label="Max Trade Size"
                    hint="Maximum size of a single order in USDT. Reduces exposure on any single signal."
                >
                    <NumberInput value={maxTradeSize} onChange={setMaxTradeSize} min={1} max={100000} step={1} suffix="USDT" />
                </Field>
            </SectionCard>

            {/* Save */}
            <div className="flex items-center gap-3">
                <button
                    onClick={handleSave}
                    className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold
                     bg-cyan-600 hover:bg-cyan-500 text-white transition-all active:scale-95
                     shadow-lg shadow-cyan-900/30"
                >
                    <Save className="w-4 h-4" />
                    Save Settings
                </button>
                {saved && (
                    <span className="flex items-center gap-1.5 text-sm text-emerald-400 animate-in fade-in duration-200">
                        <CheckCircle2 className="w-4 h-4" />
                        Saved!
                    </span>
                )}
            </div>
        </div>
    );
}
