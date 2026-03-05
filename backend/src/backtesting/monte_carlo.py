"""
Phase 49 - Monte Carlo Simulation Engine
==========================================
Stress-tests the strategy's "Risk of Ruin" by running 10,000 random-walk
simulations using the actual historical distribution of trade PnL percentages
from the stress test.

How it works:
  1. Load the 202 real trade PnL percentages from stress_test_trades.csv.
  2. For each of 10,000 simulations:
     - Start with $10,000 base capital.
     - Sample N trades (with replacement) from the real PnL distribution.
     - Compute the cumulative equity curve.
     - Track max drawdown per simulation.
  3. Produce risk metrics:
     - Median final balance.
     - 5th / 25th / 75th / 95th percentile final balances.
     - 95% Confidence Max Drawdown.
     - Risk of Ruin (% of runs where balance drops >= 50%).
  4. Generate a "spaghetti chart" PNG showing 200 random equity curves.
  5. Print a rich terminal report with a FINAL VERDICT.

Verdict:
  Risk of Ruin < 1%  ->  CLEARED FOR LIVE DEPLOYMENT
  Risk of Ruin >= 1% ->  NOT CLEARED - Review strategy parameters

Run:
  cd c:\\Users\\andko\\Desktop\\sniper_bot
  python -m backend.src.backtesting.monte_carlo
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.panel import Panel
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None  # type: ignore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INITIAL_BALANCE  = 10_000.0
N_SIMULATIONS    = 10_000
TRADES_PER_SIM   = 200          # Number of trades sampled per simulation
RUIN_THRESHOLD   = 0.50         # 50% drawdown = "ruin"
CHART_SAMPLE     = 200          # How many curves to show on spaghetti chart
FEE_PCT          = 0.002        # 0.2% round-trip fees (already in PnL data, so 0)

TRADES_CSV = Path(__file__).resolve().parent.parent / "scripts" / "stress_test_trades.csv"
OUTPUT_DIR = Path(__file__).resolve().parent
CHART_FILE = OUTPUT_DIR / "monte_carlo_cone.png"

# ---------------------------------------------------------------------------
# 1. Load Trade PnL Distribution
# ---------------------------------------------------------------------------

def load_pnl_distribution() -> np.ndarray:
    """
    Load the real PnL percentages from the stress test trade log.
    Only EXIT rows have pnl_pct filled.
    Returns a numpy array of PnL percentages (e.g., +4.75, -2.32, ...).
    """
    if not TRADES_CSV.exists():
        print(f"  ERROR: {TRADES_CSV} not found. Run stress_test.py first.")
        sys.exit(1)

    df = pd.read_csv(TRADES_CSV)
    # Only EXIT rows have pnl_pct
    exit_rows = df[df["action"] == "EXIT"].copy()
    pnl_array = exit_rows["pnl_pct"].dropna().values.astype(float)

    print(f"  Loaded {len(pnl_array)} trade PnL values from stress test")
    print(f"  PnL range: [{pnl_array.min():+.2f}% ... {pnl_array.max():+.2f}%]")
    print(f"  Mean PnL:  {pnl_array.mean():+.3f}%")
    print(f"  Std Dev:   {pnl_array.std():.3f}%")

    return pnl_array


# ---------------------------------------------------------------------------
# 2. Monte Carlo Simulation Engine
# ---------------------------------------------------------------------------

def run_monte_carlo(pnl_dist: np.ndarray) -> dict:
    """
    Run N_SIMULATIONS Monte Carlo simulations.

    Returns a dict with:
      - final_balances: (N_SIMULATIONS,) array
      - all_curves: (N_SIMULATIONS, TRADES_PER_SIM+1) array of equity curves
      - max_drawdowns: (N_SIMULATIONS,) array of max drawdown per sim
    """
    rng = np.random.default_rng(seed=42)

    # Pre-allocate arrays for speed
    all_curves     = np.zeros((N_SIMULATIONS, TRADES_PER_SIM + 1))
    max_drawdowns  = np.zeros(N_SIMULATIONS)

    all_curves[:, 0] = INITIAL_BALANCE

    t0 = time.time()
    progress_interval = N_SIMULATIONS // 10

    for sim in range(N_SIMULATIONS):
        # Sample TRADES_PER_SIM trades with replacement from real distribution
        sampled_pnl = rng.choice(pnl_dist, size=TRADES_PER_SIM, replace=True)

        # Convert PnL % to multiplicative returns: +4.75% -> 1.0475
        returns = 1.0 + sampled_pnl / 100.0

        # Compute cumulative equity
        equity = INITIAL_BALANCE * np.cumprod(returns)
        all_curves[sim, 1:] = equity

        # Max drawdown
        running_peak = np.maximum.accumulate(equity)
        drawdowns = (running_peak - equity) / running_peak * 100
        max_drawdowns[sim] = drawdowns.max()

        if (sim + 1) % progress_interval == 0:
            elapsed = time.time() - t0
            pct_done = (sim + 1) / N_SIMULATIONS * 100
            sys.stdout.write(
                f"\r  Simulation {sim+1:>6,}/{N_SIMULATIONS:,} "
                f"({pct_done:.0f}%) | {elapsed:.1f}s elapsed"
            )
            sys.stdout.flush()

    elapsed = time.time() - t0
    print(f"\n  All {N_SIMULATIONS:,} simulations completed in {elapsed:.2f}s\n")

    final_balances = all_curves[:, -1]

    return {
        "final_balances": final_balances,
        "all_curves":     all_curves,
        "max_drawdowns":  max_drawdowns,
    }


# ---------------------------------------------------------------------------
# 3. Risk Metrics
# ---------------------------------------------------------------------------

def compute_metrics(results: dict) -> dict:
    """Compute all Monte Carlo risk metrics."""
    fb = results["final_balances"]
    dd = results["max_drawdowns"]

    # Percentiles of final balance
    p5, p25, p50, p75, p95 = np.percentile(fb, [5, 25, 50, 75, 95])

    # Mean and std
    mean_balance = fb.mean()
    std_balance  = fb.std()

    # Max drawdown percentiles
    dd_mean = dd.mean()
    dd_95   = np.percentile(dd, 95)
    dd_max  = dd.max()

    # Risk of Ruin: how many sims had balance drop >= 50% from peak at any point
    ruin_count  = np.sum(dd >= RUIN_THRESHOLD * 100)   # dd is in %, threshold is 50%
    risk_of_ruin = ruin_count / len(dd) * 100

    # Probability of profit: % of sims that ended above starting capital
    profitable = np.sum(fb > INITIAL_BALANCE)
    prob_profit = profitable / len(fb) * 100

    # CAGR estimate (200 trades ~ 3 years)
    median_return = (p50 / INITIAL_BALANCE - 1) * 100

    return {
        "n_simulations":   N_SIMULATIONS,
        "trades_per_sim":  TRADES_PER_SIM,
        "mean_balance":    mean_balance,
        "std_balance":     std_balance,
        "p5_balance":      p5,
        "p25_balance":     p25,
        "median_balance":  p50,
        "p75_balance":     p75,
        "p95_balance":     p95,
        "dd_mean":         dd_mean,
        "dd_95":           dd_95,
        "dd_max":          dd_max,
        "ruin_count":      int(ruin_count),
        "risk_of_ruin":    risk_of_ruin,
        "prob_profit":     prob_profit,
        "median_return":   median_return,
    }


# ---------------------------------------------------------------------------
# 4. Spaghetti Chart (Matplotlib)
# ---------------------------------------------------------------------------

def generate_chart(results: dict, metrics: dict) -> None:
    """Generate the Monte Carlo probability cone spaghetti chart."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter
    except ImportError:
        print("  WARNING: matplotlib not installed. Skipping chart generation.")
        print("  Install with: pip install matplotlib")
        return

    all_curves = results["all_curves"]
    n_sims = all_curves.shape[0]

    # Select a random sample for the spaghetti plot
    rng = np.random.default_rng(seed=123)
    sample_idx = rng.choice(n_sims, size=min(CHART_SAMPLE, n_sims), replace=False)

    x = np.arange(TRADES_PER_SIM + 1)

    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    # Percentile bands (probability cone)
    p5  = np.percentile(all_curves, 5,  axis=0)
    p25 = np.percentile(all_curves, 25, axis=0)
    p50 = np.percentile(all_curves, 50, axis=0)
    p75 = np.percentile(all_curves, 75, axis=0)
    p95 = np.percentile(all_curves, 95, axis=0)

    ax.fill_between(x, p5, p95, alpha=0.15, color="#58a6ff", label="5th-95th percentile")
    ax.fill_between(x, p25, p75, alpha=0.25, color="#58a6ff", label="25th-75th percentile")

    # Spaghetti curves (individual simulations)
    for idx in sample_idx:
        curve = all_curves[idx]
        final = curve[-1]
        color = "#3fb950" if final > INITIAL_BALANCE else "#f85149"
        ax.plot(x, curve, color=color, alpha=0.08, linewidth=0.5)

    # Median line (prominent)
    ax.plot(x, p50, color="#f0c000", linewidth=2.5, label="Median", zorder=10)

    # Starting capital reference
    ax.axhline(y=INITIAL_BALANCE, color="#8b949e", linewidth=1.0,
               linestyle="--", alpha=0.7, label=f"Start (${INITIAL_BALANCE:,.0f})")

    # Ruin line
    ruin_line = INITIAL_BALANCE * (1 - RUIN_THRESHOLD)
    ax.axhline(y=ruin_line, color="#f85149", linewidth=1.5,
               linestyle=":", alpha=0.8, label=f"Ruin (${ruin_line:,.0f})")

    # Formatting
    ax.set_title(
        f"Phase 49 - Monte Carlo Simulation ({N_SIMULATIONS:,} runs, {TRADES_PER_SIM} trades each)",
        fontsize=16, color="#c9d1d9", fontweight="bold", pad=15
    )
    ax.set_xlabel("Trade Number", fontsize=12, color="#8b949e")
    ax.set_ylabel("Portfolio Value ($)", fontsize=12, color="#8b949e")

    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.tick_params(colors="#8b949e")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#30363d")
    ax.spines["left"].set_color("#30363d")
    ax.grid(axis="y", alpha=0.15, color="#30363d")

    # Legend
    legend = ax.legend(loc="upper left", fontsize=10, facecolor="#161b22",
                       edgecolor="#30363d", labelcolor="#c9d1d9")

    # Stats annotation box
    ror = metrics["risk_of_ruin"]
    verdict_color = "#3fb950" if ror < 1.0 else "#f85149"
    verdict_text = "CLEARED" if ror < 1.0 else "NOT CLEARED"
    stats_text = (
        f"Median Final: ${metrics['median_balance']:,.0f}\n"
        f"95% CI DD: {metrics['dd_95']:.1f}%\n"
        f"Risk of Ruin: {ror:.2f}%\n"
        f"Verdict: {verdict_text}"
    )
    props = dict(boxstyle="round,pad=0.5", facecolor="#161b22",
                 edgecolor=verdict_color, alpha=0.9)
    ax.text(0.98, 0.02, stats_text, transform=ax.transAxes, fontsize=10,
            verticalalignment="bottom", horizontalalignment="right",
            color=verdict_color, bbox=props, family="monospace")

    plt.tight_layout()
    plt.savefig(str(CHART_FILE), dpi=150, facecolor="#0d1117")
    plt.close()
    print(f"  Spaghetti chart saved to: {CHART_FILE}")


# ---------------------------------------------------------------------------
# 5. Rich Terminal Report
# ---------------------------------------------------------------------------

def print_report(metrics: dict, pnl_dist: np.ndarray) -> None:
    """Print a premium terminal report."""
    ror = metrics["risk_of_ruin"]
    cleared = ror < 1.0

    if _RICH:
        console.print()
        console.rule("[bold cyan]PHASE 49 - MONTE CARLO SIMULATION REPORT[/bold cyan]")
        console.print(
            f"  [dim]{N_SIMULATIONS:,} simulations | {TRADES_PER_SIM} trades/sim | "
            f"{len(pnl_dist)} real PnL samples | Start: ${INITIAL_BALANCE:,.0f}[/dim]\n"
        )

        # Input distribution table
        dist_table = Table(
            title="Input: Real PnL Distribution (from 202 Stress Test Trades)",
            box=box.ROUNDED, show_header=False,
        )
        dist_table.add_column("Metric", style="bold yellow", width=32)
        dist_table.add_column("Value",  justify="right",     width=18)
        dist_table.add_row("Total Trades", str(len(pnl_dist)))
        dist_table.add_row("Mean PnL per Trade",  f"{pnl_dist.mean():+.3f}%")
        dist_table.add_row("Std Dev",              f"{pnl_dist.std():.3f}%")
        dist_table.add_row("Min PnL (worst)",      f"{pnl_dist.min():+.2f}%")
        dist_table.add_row("Max PnL (best)",       f"{pnl_dist.max():+.2f}%")
        dist_table.add_row("Win Rate",             f"{(pnl_dist > 0).sum() / len(pnl_dist) * 100:.1f}%")
        console.print(dist_table)
        console.print()

        # Monte Carlo results table
        mc_table = Table(
            title="Monte Carlo Results (10,000 Simulations)",
            box=box.DOUBLE_EDGE, show_header=False,
        )
        mc_table.add_column("Metric", style="bold cyan", width=38)
        mc_table.add_column("Value",  justify="right",   width=22)

        mc_table.add_row("Median Final Balance",     f"${metrics['median_balance']:,.0f}")
        mc_table.add_row("Mean Final Balance",        f"${metrics['mean_balance']:,.0f}")
        mc_table.add_row("5th Percentile (worst 5%)", f"${metrics['p5_balance']:,.0f}")
        mc_table.add_row("25th Percentile",           f"${metrics['p25_balance']:,.0f}")
        mc_table.add_row("75th Percentile",           f"${metrics['p75_balance']:,.0f}")
        mc_table.add_row("95th Percentile (best 5%)", f"${metrics['p95_balance']:,.0f}")
        mc_table.add_row("", "")
        mc_table.add_row("Probability of Profit",     f"{metrics['prob_profit']:.1f}%")
        mc_table.add_row("Median Return",             f"{metrics['median_return']:+.1f}%")
        console.print(mc_table)
        console.print()

        # Risk metrics table
        risk_table = Table(
            title="Risk Assessment",
            box=box.HEAVY, show_header=False,
        )
        risk_table.add_column("Metric", style="bold red", width=38)
        risk_table.add_column("Value",  justify="right",  width=22)

        risk_table.add_row("Avg Max Drawdown",       f"{metrics['dd_mean']:.2f}%")
        risk_table.add_row("95% CI Max Drawdown",    f"{metrics['dd_95']:.2f}%")
        risk_table.add_row("Absolute Max Drawdown",  f"{metrics['dd_max']:.2f}%")
        risk_table.add_row("", "")

        ror_style = "green" if cleared else "red bold"
        risk_table.add_row(
            "Ruin Events (balance -50%+)",
            f"{metrics['ruin_count']} / {N_SIMULATIONS:,}"
        )
        risk_table.add_row(
            "RISK OF RUIN",
            f"[{ror_style}]{ror:.3f}%[/{ror_style}]"
        )
        console.print(risk_table)
        console.print()

        # Final verdict
        console.rule()
        if cleared:
            console.print(Panel(
                "[bold green]CLEARED FOR LIVE DEPLOYMENT[/bold green]\n\n"
                f"[dim]Risk of Ruin ({ror:.3f}%) is below the 1% threshold.\n"
                f"The strategy is statistically robust enough for real capital.[/dim]",
                title="[bold green]FINAL VERDICT[/bold green]",
                border_style="green", expand=False, width=60
            ))
        else:
            console.print(Panel(
                "[bold red]NOT CLEARED - REVIEW STRATEGY PARAMETERS[/bold red]\n\n"
                f"[dim]Risk of Ruin ({ror:.2f}%) exceeds the 1% safety threshold.\n"
                f"Consider tighter stop losses or reduced position sizes.[/dim]",
                title="[bold red]FINAL VERDICT[/bold red]",
                border_style="red", expand=False, width=60
            ))
        console.rule()
        console.print()

    else:
        # ASCII fallback
        W = 76
        print()
        print("  " + "=" * W)
        print("  ||" + " PHASE 49 - MONTE CARLO SIMULATION REPORT ".center(W - 4) + "||")
        print("  " + "=" * W)

        print(f"\n  +{'---'*25}+")
        print(f"  | {'MONTE CARLO RESULTS':^{W-4}} |")
        print(f"  +{'---'*25}+")
        print(f"  | Median Final Balance:    ${metrics['median_balance']:>12,.0f}          |")
        print(f"  | 5th Percentile:          ${metrics['p5_balance']:>12,.0f}          |")
        print(f"  | 95th Percentile:         ${metrics['p95_balance']:>12,.0f}          |")
        print(f"  | Probability of Profit:   {metrics['prob_profit']:>10.1f}%            |")
        print(f"  | 95% CI Max Drawdown:     {metrics['dd_95']:>10.2f}%            |")
        print(f"  | Risk of Ruin:            {ror:>10.3f}%            |")
        print(f"  +{'---'*25}+")

        verdict = "CLEARED FOR LIVE DEPLOYMENT" if cleared else "NOT CLEARED"
        marker = "[OK]" if cleared else "[!!]"
        print()
        print("  " + "=" * W)
        print(f"  || {marker} FINAL VERDICT: {verdict:<{W-23}}||")
        print("  " + "=" * W)
        print()


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("  " + "=" * 76)
    print("  ||" + " PHASE 49 - MONTE CARLO SIMULATION ENGINE ".center(72) + "||")
    print("  ||" + f" {N_SIMULATIONS:,} simulations | {TRADES_PER_SIM} trades/sim | Real PnL data ".center(72) + "||")
    print("  " + "=" * 76)

    # 1. Load PnL distribution
    print("\n  STEP 1: LOADING TRADE PnL DISTRIBUTION")
    print("  " + "-" * 50)
    pnl_dist = load_pnl_distribution()

    # 2. Run simulations
    print("\n  STEP 2: RUNNING MONTE CARLO SIMULATIONS")
    print("  " + "-" * 50)
    results = run_monte_carlo(pnl_dist)

    # 3. Compute metrics
    print("  STEP 3: COMPUTING RISK METRICS")
    print("  " + "-" * 50)
    metrics = compute_metrics(results)

    # 4. Generate chart
    print("\n  STEP 4: GENERATING SPAGHETTI CHART")
    print("  " + "-" * 50)
    generate_chart(results, metrics)

    # 5. Print report
    print_report(metrics, pnl_dist)


if __name__ == "__main__":
    main()
