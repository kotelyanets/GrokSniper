import type { Metadata } from "next";
import { Syne, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import NavLinks from "@/components/NavLinks";
import KillSwitchButton from "@/components/KillSwitchButton";
import Link from "next/link";

const syne = Syne({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-syne",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GrokSniper AI — Institutional Trading Terminal",
  description: "AI-driven crypto algorithmic trading system with multi-agent Board of Directors architecture",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${syne.variable} ${jetbrainsMono.variable} min-h-screen antialiased overflow-x-hidden`}
        style={{ fontFamily: "var(--font-syne, 'Syne'), sans-serif" }}>

        {/* ── Ambient background effects ────────────────────────────────── */}
        <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden" aria-hidden>
          {/* Deep space gradient */}
          <div style={{
            position: "absolute",
            inset: 0,
            background: "radial-gradient(ellipse 120% 80% at 50% -10%, rgba(0,212,255,0.06) 0%, transparent 60%), radial-gradient(ellipse 60% 60% at 0% 100%, rgba(139,92,246,0.05) 0%, transparent 50%), #080b0f"
          }} />
          {/* Grid overlay */}
          <div className="grid-bg absolute inset-0 opacity-60" />
          {/* Horizontal scan line that slowly drifts */}
          <div style={{
            position: "absolute",
            left: 0,
            right: 0,
            height: "1px",
            background: "linear-gradient(90deg, transparent, rgba(0,212,255,0.3), transparent)",
            animation: "scanline 8s linear infinite",
            top: "30%"
          }} />
        </div>

        <div style={{ display: "flex", minHeight: "100vh", position: "relative", zIndex: 10 }}>
          {/* ── Lateral Navigation (Sidebar) ────────────────────────────── */}
          <aside style={{
            position: "sticky",
            top: 0,
            height: "100vh",
            width: "260px",
            flexShrink: 0,
            borderRight: "1px solid rgba(0,212,255,0.1)",
            background: "rgba(8,11,15,0.7)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            display: "flex",
            flexDirection: "column",
            zIndex: 50,
            boxShadow: "4px 0 24px rgba(0,0,0,0.4)"
          }}>
            {/* Logo Area */}
            <div style={{ padding: "32px 24px", borderBottom: "1px solid rgba(0,212,255,0.05)" }}>
              <Link href="/" style={{ display: "flex", alignItems: "center", gap: "14px", textDecoration: "none" }}>
                {/* Logo mark — crosshair/sniper target */}
                <div style={{
                  width: "42px", height: "42px", borderRadius: "10px", flexShrink: 0,
                  background: "linear-gradient(135deg, #0a1628 0%, #0d2040 100%)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  boxShadow: "0 0 20px rgba(0,212,255,0.25), inset 0 0 0 1px rgba(0,212,255,0.3)",
                  position: "relative", overflow: "hidden"
                }}>
                  <svg width="24" height="24" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="10" cy="10" r="7.5" stroke="#00d4ff" strokeWidth="1.2" />
                    <circle cx="10" cy="10" r="1.8" fill="#00d4ff" />
                    <line x1="10" y1="2" x2="10" y2="6.5" stroke="#00d4ff" strokeWidth="1.2" strokeLinecap="round" />
                    <line x1="10" y1="13.5" x2="10" y2="18" stroke="#00d4ff" strokeWidth="1.2" strokeLinecap="round" />
                    <line x1="2" y1="10" x2="6.5" y2="10" stroke="#00d4ff" strokeWidth="1.2" strokeLinecap="round" />
                    <line x1="13.5" y1="10" x2="18" y2="10" stroke="#00d4ff" strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                </div>
                {/* Brand name */}
                <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
                  <span style={{ fontFamily: "var(--font-syne)", fontWeight: 800, fontSize: "16px", letterSpacing: "0.08em", color: "#e8edf2", textTransform: "uppercase" }}>
                    GrokSniper
                  </span>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontWeight: 400, fontSize: "10px", letterSpacing: "0.2em", color: "var(--cyan)", textTransform: "uppercase", marginTop: "2px" }}>
                    AI Terminal v2
                  </span>
                </div>
              </Link>
            </div>

            {/* Navigation Area */}
            <div style={{ padding: "32px 16px", flexGrow: 1, overflowY: "auto" }}>
              <div style={{
                fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 700,
                letterSpacing: "0.15em", color: "#4a5568", marginBottom: "16px", paddingLeft: "8px"
              }}>
                MAIN MENU
              </div>
              <NavLinks />
            </div>

            {/* Bottom Controls */}
            <div style={{ padding: "24px 16px", borderTop: "1px solid rgba(0,212,255,0.05)", display: "flex", flexDirection: "column", gap: "16px" }}>
              {/* Live indicator */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: "8px",
                padding: "12px", borderRadius: "8px",
                background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)",
                fontFamily: "var(--font-jetbrains)", fontSize: "11px", fontWeight: 700,
                color: "var(--green)", letterSpacing: "0.15em", textTransform: "uppercase"
              }}>
                <span className="pulse-dot green" style={{ width: "6px", height: "6px" }} />
                SYSTEM LIVE
              </div>

              {/* Kill Switch Wrapper */}
              <div style={{ display: "flex", justifyContent: "center", width: "100%" }}>
                <KillSwitchButton />
              </div>
            </div>
          </aside>

          {/* ── Main content Wrapper ──────────────────────────────────────── */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
            {/* Page Content */}
            <main style={{ flex: 1, width: "100%", maxWidth: "1600px", margin: "0 auto", padding: "40px" }}>
              {children}
            </main>

            {/* Footer */}
            <footer style={{
              borderTop: "1px solid var(--border)",
              padding: "20px 40px", textAlign: "left",
              fontFamily: "var(--font-jetbrains)", fontSize: "11px",
              color: "var(--text-muted)", letterSpacing: "0.05em",
              display: "flex", justifyContent: "space-between", alignItems: "center"
            }}>
              <span>GrokSniper AI © 2026</span>
              <span>Institutional Algorithmic Trading System · Paper Trading Mode</span>
            </footer>
          </div>
        </div>

        <style>{`
          @keyframes scanline {
            0%   { top: -2px; opacity: 0; }
            10%  { opacity: 1; }
            90%  { opacity: 0.6; }
            100% { top: 100%; opacity: 0; }
          }
        `}</style>
      </body>
    </html>
  );
}
