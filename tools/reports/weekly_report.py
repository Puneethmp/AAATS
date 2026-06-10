"""
Weekly honest-PnL report generator (forensic-audit Phase 4).

Emits REPORTS/week_NN.md from the paper-trade ledger, re-priced NET of costs and
benchmarked against the no-trade baseline. The mandate forbids gross-only
reporting; this generator only ever prints net numbers + the baseline gap.

Usage:
    python tools/reports/weekly_report.py [--db runtime/paper_trades.db] \
        [--since 2026-06-03T00:00:00+00:00] [--until ...] [--week NN] [--out REPORTS]

Pure-ish: reads the DB, writes one markdown file. No network, no live state.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Repo-root bootstrap (matches tools/operator/* convention) so the script runs
# directly as `python tools/reports/weekly_report.py` as well as under pytest.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from analytics.ledger_repricer import reprice_ledger, no_trade_baseline  # noqa: E402


def _recurring_flags(db_path: str, since: str | None, until: str | None) -> list[str]:
    """Surface recurring failure patterns (the raw material for the monthly
    hypothesis cycle). Computed, not hand-written."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        q = "SELECT strategy, pnl, notes, note FROM paper_trades WHERE pnl IS NOT NULL AND pnl < 0"
        params: list = []
        if since:
            q += " AND timestamp >= ?"
            params.append(since)
        if until:
            q += " AND timestamp <= ?"
            params.append(until)
        rows = [dict(r) for r in conn.execute(q, params)]
    finally:
        conn.close()

    reasons: Counter = Counter()
    by_strat: Counter = Counter()
    for r in rows:
        by_strat[r.get("strategy") or "UNKNOWN"] += 1
        try:
            er = (json.loads(r.get("notes") or "{}").get("exit_reason") or "").split(
                "("
            )[0]
        except Exception:
            er = ""
        reasons[er or "none"] += 1

    flags: list[str] = []
    total = sum(reasons.values()) or 1
    for reason, n in reasons.most_common(3):
        pct = 100.0 * n / total
        if pct >= 25.0:
            flags.append(f"{pct:.0f}% of losing exits are `{reason}` ({n}/{total})")
    for strat, n in by_strat.most_common(1):
        flags.append(f"most losses concentrated in {strat} ({n})")
    return flags


def generate(db_path: str, week: int, since: str | None, until: str | None) -> str:
    rep = reprice_ledger(db_path, since=since, until=until)
    d = rep.as_dict()
    baseline = no_trade_baseline()
    gap = rep.total_net - baseline
    flags = _recurring_flags(db_path, since, until)

    lines: list[str] = []
    lines.append(f"# Weekly Report — week {week:02d}")
    lines.append("")
    lines.append(
        f"> Window: {d['window_start']} -> {d['window_end']} | events: {d['n_events']}"
    )
    lines.append(
        "> All PnL NET of fees + slippage (+ funding for perps). Gross-only is never reported."
    )
    lines.append("")
    lines.append("## PnL vs no-trade baseline")
    lines.append("")
    lines.append("| Measure | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Net PnL (all strategies) | {d['total_net']:+.4f} |")
    lines.append(f"| Gross PnL (reference only) | {d['total_gross']:+.4f} |")
    lines.append(f"| No-trade baseline | {baseline:+.4f} |")
    lines.append(f"| **Gap vs no-trade** | **{gap:+.4f}** |")
    lines.append(f"| Beats no-trade? | {'YES' if rep.beats_no_trade() else 'NO'} |")
    cr = d["cost_ratio"]
    lines.append(
        f"| Cost ratio (costs / winners' gross) | {('n/a' if cr is None else f'{cr:.2f}')} |"
    )
    lines.append("")
    lines.append("## Per-strategy (net of costs)")
    lines.append("")
    lines.append(
        "| Strategy | n | gross | fees | slippage | funding | net | beats no-trade |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|:--:|")
    for s in sorted(d["per_strategy"].values(), key=lambda x: x["net"]):
        lines.append(
            f"| {s['strategy']} | {s['n']} | {s['gross']:+.3f} | {s['fees']:.3f} | "
            f"{s['slippage']:.3f} | {s['funding']:.3f} | {s['net']:+.3f} | "
            f"{'YES' if s['net'] > 0 else 'NO'} |"
        )
    lines.append("")
    lines.append("## Loss-bucket distribution")
    lines.append("")
    lines.append("| Bucket | n | net |")
    lines.append("|---|---:|---:|")
    for b, v in sorted(d["buckets"].items(), key=lambda x: x[1]["net"]):
        lines.append(f"| {b} | {v['n']} | {v['net']:+.4f} |")
    lines.append("")
    lines.append("## Recurring failure-pattern flags (-> monthly hypothesis cycle)")
    lines.append("")
    if flags:
        for f in flags:
            lines.append(f"- {f}")
    else:
        lines.append("- (none crossed the 25% threshold this window)")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if rep.beats_no_trade():
        lines.append("Net positive and beats the no-trade baseline this window.")
    else:
        lines.append(
            "Does NOT beat the no-trade baseline. Per the program rule, a flat week "
            "beats a losing week — strategies failing to clear $0 net are candidates "
            "for demotion."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="runtime/paper_trades.db")
    ap.add_argument("--since", default=None)
    ap.add_argument("--until", default=None)
    ap.add_argument("--week", type=int, default=1)
    ap.add_argument("--out", default="REPORTS")
    args = ap.parse_args()

    md = generate(args.db, args.week, args.since, args.until)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"week_{args.week:02d}.md"
    path.write_text(md, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
