"use client";

export default function KillSwitchButton() {
    return (
        <form action="/api/pause" method="POST" style={{ width: "100%" }}>
            <button
                type="submit"
                style={{
                    display: "flex", alignItems: "center", justifyContent: "center", gap: "10px",
                    width: "100%",
                    padding: "12px 14px", borderRadius: "8px",
                    background: "rgba(239,68,68,0.08)",
                    border: "1px solid rgba(239,68,68,0.25)",
                    color: "#ef4444",
                    fontFamily: "var(--font-jetbrains, 'JetBrains Mono', monospace)",
                    fontSize: "12px", fontWeight: 700,
                    letterSpacing: "0.15em", textTransform: "uppercase",
                    cursor: "pointer",
                    transition: "all 0.2s cubic-bezier(0.23, 1, 0.32, 1)",
                    boxShadow: "0 4px 12px rgba(239,68,68,0.05)"
                }}
                title="Emergency Stop — halt all bot activity"
                onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "rgba(239,68,68,0.15)";
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(239,68,68,0.5)";
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 8px 16px rgba(239,68,68,0.15), inset 0 0 12px rgba(239,68,68,0.1)";
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
                }}
                onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "rgba(239,68,68,0.08)";
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "rgba(239,68,68,0.25)";
                    (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 4px 12px rgba(239,68,68,0.05)";
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
                }}
            >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
                    <rect x="3.5" y="1" width="3" height="8" rx="1" />
                    <rect x="1" y="3.5" width="8" height="3" rx="1" />
                </svg>
                Kill
            </button>
        </form>
    );
}
