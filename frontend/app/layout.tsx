import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import NavLinks from "@/components/NavLinks";
import KillSwitchButton from "@/components/KillSwitchButton";
import Link from "next/link";

const inter = Inter({
  subsets: ["latin", "cyrillic"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GrokSniper AI — Trading Dashboard",
  description: "AI-driven crypto algorithmic trading system with multi-agent architecture",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} min-h-screen antialiased overflow-x-hidden`}
        style={{ fontFamily: "var(--font-inter, 'Inter', system-ui, sans-serif)" }}
      >
        <div style={{ display: "flex", minHeight: "100vh" }}>

          {/* ── Sidebar ──────────────────────────────────────────────── */}
          <aside style={{
            position: "sticky",
            top: 0,
            height: "100vh",
            width: "240px",
            flexShrink: 0,
            borderRight: "1px solid var(--border)",
            background: "rgba(9, 9, 11, 0.85)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            display: "flex",
            flexDirection: "column",
            zIndex: 50,
          }}>
            {/* Logo */}
            <div style={{ padding: "28px 20px", borderBottom: "1px solid var(--border)" }}>
              <Link href="/" style={{ display: "flex", alignItems: "center", gap: "12px", textDecoration: "none" }}>
                <div style={{
                  width: "36px", height: "36px", borderRadius: "8px", flexShrink: 0,
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid var(--border)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="10" cy="10" r="7" stroke="#a1a1aa" strokeWidth="1.2" />
                    <circle cx="10" cy="10" r="1.5" fill="#fafafa" />
                    <line x1="10" y1="2.5" x2="10" y2="6.5" stroke="#a1a1aa" strokeWidth="1" strokeLinecap="round" />
                    <line x1="10" y1="13.5" x2="10" y2="17.5" stroke="#a1a1aa" strokeWidth="1" strokeLinecap="round" />
                    <line x1="2.5" y1="10" x2="6.5" y2="10" stroke="#a1a1aa" strokeWidth="1" strokeLinecap="round" />
                    <line x1="13.5" y1="10" x2="17.5" y2="10" stroke="#a1a1aa" strokeWidth="1" strokeLinecap="round" />
                  </svg>
                </div>
                <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
                  <span style={{ fontWeight: 600, fontSize: "15px", letterSpacing: "-0.01em", color: "var(--text-primary)" }}>
                    GrokSniper
                  </span>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "10px", color: "var(--text-muted)", letterSpacing: "0.05em" }}>
                    v2.0
                  </span>
                </div>
              </Link>
            </div>

            {/* Navigation */}
            <div style={{ padding: "24px 12px", flexGrow: 1, overflowY: "auto" }}>
              <div style={{
                fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 500,
                letterSpacing: "0.12em", color: "var(--text-muted)", marginBottom: "12px", paddingLeft: "8px",
                textTransform: "uppercase",
              }}>
                Navigation
              </div>
              <NavLinks />
            </div>

            {/* Bottom Controls */}
            <div style={{ padding: "16px 12px", borderTop: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: "12px" }}>
              {/* Live indicator */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "center", gap: "8px",
                padding: "10px", borderRadius: "8px",
                background: "var(--green-dim)",
                fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 600,
                color: "var(--green)", letterSpacing: "0.1em", textTransform: "uppercase",
              }}>
                <span
                  className="pulse-soft"
                  style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--green)", display: "inline-block" }}
                />
                System Live
              </div>
              <KillSwitchButton />
            </div>
          </aside>

          {/* ── Main Content ─────────────────────────────────────────── */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
            <main style={{ flex: 1, width: "100%", maxWidth: "1440px", margin: "0 auto", padding: "32px" }}>
              {children}
            </main>

            {/* Footer */}
            <footer style={{
              borderTop: "1px solid var(--border)",
              padding: "16px 32px",
              fontFamily: "var(--font-mono)", fontSize: "11px",
              color: "var(--text-muted)",
              display: "flex", justifyContent: "space-between",
            }}>
              <span>GrokSniper AI © 2026</span>
              <span>Algorithmic Trading System</span>
            </footer>
          </div>
        </div>
      </body>
    </html>
  );
}
