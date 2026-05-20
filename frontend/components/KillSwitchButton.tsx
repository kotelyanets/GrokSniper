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
                    background: "rgba(244, 63, 94, 0.06)",
                    border: "1px solid rgba(244, 63, 94, 0.12)",
                    color: "#fb7185",
                    fontFamily: "var(--font-jetbrains, 'JetBrains Mono', monospace)",
                    fontSize: "12px", fontWeight: 700,
                    letterSpacing: "0.15em", textTransform: "uppercase",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                }}
                title="Emergency Stop — halt all bot activity"
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
