import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AlertTriangle, Zap } from "lucide-react";
import { EtheralShadow } from "@/components/ui/etheral-shadow";
import NavLinks from "@/components/NavLinks";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "GrokSniper AI — Trading Terminal",
  description: "Algorithmic crypto trading bot dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} text-white min-h-screen antialiased overflow-x-hidden bg-gray-950`}>
        <EtheralShadow
          color="rgba(0, 180, 216, 0.1)"
          animation={{ scale: 80, speed: 40 }}
          noise={{ opacity: 0.8, scale: 1 }}
          sizing="fill"
          className="flex flex-col min-h-screen w-full"
        >
          {/* ── Top Navigation ─────────────────────────────────────────── */}
          <header className="sticky top-0 z-50 border-b border-gray-800/60 bg-gray-950/20 backdrop-blur-xl">
            <div className="max-w-screen-2xl mx-auto px-6 h-16 flex items-center justify-between">
              {/* Logo */}
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-violet-500 flex items-center justify-center shadow-lg shadow-cyan-500/30">
                  <Zap className="w-4 h-4 text-white" strokeWidth={2.5} />
                </div>
                <div className="flex flex-col leading-none">
                  <span className="text-sm font-bold tracking-widest text-white uppercase">
                    GrokSniper
                  </span>
                  <span className="text-[10px] tracking-[0.2em] text-cyan-400 uppercase font-medium">
                    AI Terminal
                  </span>
                </div>
              </div>

              {/* Nav — client component for active state */}
              <NavLinks />

              {/* Kill Switch */}
              <button
                className="flex items-center gap-2 px-4 py-2 rounded-lg
                           bg-red-950/60 border border-red-800/60 text-red-400
                           hover:bg-red-900/70 hover:border-red-600/80 hover:text-red-300
                           active:scale-95 transition-all duration-150 font-medium text-sm
                           shadow-lg shadow-red-900/20"
                title="Emergency Stop — halt all bot activity"
              >
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-60" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
                </span>
                <AlertTriangle className="w-4 h-4" strokeWidth={2} />
                <span className="hidden sm:inline">Kill Switch</span>
              </button>
            </div>
          </header>

          {/* ── Page Content ───────────────────────────────────────────── */}
          <main className="flex-1 max-w-screen-2xl w-full mx-auto px-6 py-8 relative z-10">
            {children}
          </main>
        </EtheralShadow>
      </body>
    </html>
  );
}
