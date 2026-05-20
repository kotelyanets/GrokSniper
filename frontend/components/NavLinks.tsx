"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
    { label: "Dashboard", href: "/" },
    { label: "Trades", href: "/trades" },
    { label: "Analysis", href: "/analysis" },
    { label: "Analytics", href: "/analytics" },
    { label: "Backtest", href: "/backtest" },
    { label: "Settings", href: "/settings" },
];

const ICONS: Record<string, React.ReactNode> = {
    Dashboard: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></svg>,
    Trades: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" /></svg>,
    Analysis: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>,
    Analytics: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.21 15.89A10 10 0 1 1 8 2.83" /><path d="M22 12A10 10 0 0 0 12 2v10z" /></svg>,
    Backtest: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg>,
    Settings: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>,
};

export default function NavLinks() {
    const pathname = usePathname();

    return (
        <nav style={{ display: "flex", flexDirection: "column", gap: "8px", width: "100%" }}>
            {NAV_ITEMS.map(({ label, href }) => {
                const isActive = href === "/" ? pathname === "/" : pathname.startsWith(href);
                return (
                    <Link
                        key={href}
                        href={href}
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "14px",
                            padding: "14px 18px",
                            borderRadius: "10px",
                            fontFamily: "var(--font-jetbrains, 'JetBrains Mono', monospace)",
                            fontSize: "12px",
                            fontWeight: isActive ? 600 : 500,
                            letterSpacing: "0.1em",
                            textDecoration: "none",
                            textTransform: "uppercase",
                            transition: "all 0.15s ease",
                            background: isActive ? "rgba(255, 255, 255, 0.05)" : "transparent",
                            border: "1px solid transparent",
                            borderLeft: isActive ? "2px solid rgba(255, 255, 255, 0.4)" : "2px solid transparent",
                            color: isActive ? "#fafafa" : "var(--text-muted)",
                        }}
                    >
                        <span className="nav-icon" style={{
                            color: isActive ? "#fafafa" : "var(--text-muted)",
                            transition: "color 0.15s ease",
                            display: "flex", alignItems: "center", justifyContent: "center"
                        }}>
                            {ICONS[label]}
                        </span>
                        {label}
                    </Link>
                );
            })}
        </nav>
    );
}
