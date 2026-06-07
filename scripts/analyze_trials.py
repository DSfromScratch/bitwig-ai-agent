#!/usr/bin/env python3
"""Auswertung der Trial-Harness-Läufe (w3-stats).

Liest training_data/trials/trials_*.csv und beantwortet: Lernt/profitiert der
Agent von der Knowledge-Base?

Ausgabe:
  * Mean best-score pro Tag (with_kb vs no_kb)
  * Mean score je Iteration (Konvergenz-Kurve)
  * Solve-Rate, mittlere Iterationen bis Lösung, Latenz
  * ASCII-Konvergenz-Plot (immer) + optional PNG (wenn matplotlib vorhanden)

Usage:
  python -m scripts.analyze_trials
  python -m scripts.analyze_trials --threshold 0.8 --plot
"""
from __future__ import annotations

import argparse
import csv
import glob
import statistics
from collections import defaultdict
from pathlib import Path

TRIALS_DIR = Path("training_data/trials")


def _to_float(x: str, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_rows(tag_glob: str = "trials_*.csv") -> list[dict]:
    rows: list[dict] = []
    for path in sorted(glob.glob(str(TRIALS_DIR / tag_glob))):
        tag = Path(path).stem.replace("trials_", "")
        with open(path) as f:
            for r in csv.DictReader(f):
                r["_tag"] = tag
                r["iteration"] = int(r.get("iteration") or 1)
                r["trial_id"] = int(r.get("trial_id") or 0)
                r["score"] = _to_float(r.get("score"))
                r["latency_s"] = _to_float(r.get("latency_s"))
                rows.append(r)
    return rows


def summarize(rows: list[dict], threshold: float) -> dict[str, dict]:
    """Aggregiert pro Tag: best-score je Trial, solve-rate, iter-bis-lösung, latenz."""
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tag[r["_tag"]].append(r)

    out: dict[str, dict] = {}
    for tag, trows in by_tag.items():
        best: dict[int, float] = defaultdict(float)
        solve_iter: dict[int, int] = {}
        for r in trows:
            tid = r["trial_id"]
            best[tid] = max(best[tid], r["score"])
            if r["score"] >= threshold and tid not in solve_iter:
                solve_iter[tid] = r["iteration"]
        n_trials = len(best)
        solved = len(solve_iter)
        out[tag] = {
            "n_trials": n_trials,
            "n_iterations": len(trows),
            "mean_best": statistics.mean(best.values()) if best else 0.0,
            "solve_rate": solved / n_trials if n_trials else 0.0,
            "mean_iter_to_solve": (statistics.mean(solve_iter.values())
                                   if solve_iter else float("nan")),
            "mean_latency": statistics.mean(r["latency_s"] for r in trows) if trows else 0.0,
        }
    return out


def per_iteration_means(rows: list[dict]) -> dict[str, dict[int, float]]:
    """Mean score je (tag, iteration) — Konvergenz-Kurve."""
    bucket: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in rows:
        bucket[(r["_tag"], r["iteration"])].append(r["score"])
    out: dict[str, dict[int, float]] = defaultdict(dict)
    for (tag, it), scores in bucket.items():
        out[tag][it] = statistics.mean(scores)
    return out


def ascii_plot(curves: dict[str, dict[int, float]], width: int = 40) -> str:
    """Einfacher ASCII-Konvergenz-Plot (mean score je Iteration)."""
    lines = ["", "Konvergenz (mean score je Iteration):"]
    max_it = max((it for c in curves.values() for it in c), default=1)
    for tag in sorted(curves):
        lines.append(f"  [{tag}]")
        for it in range(1, max_it + 1):
            val = curves[tag].get(it)
            if val is None:
                continue
            bar = "█" * int(round(val * width))
            lines.append(f"    it{it}: {bar:<{width}} {val:.3f}")
    return "\n".join(lines)


def maybe_png(curves: dict[str, dict[int, float]], out: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    fig, ax = plt.subplots(figsize=(7, 4))
    for tag in sorted(curves):
        xs = sorted(curves[tag])
        ys = [curves[tag][x] for x in xs]
        ax.plot(xs, ys, marker="o", label=tag)
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Mean Score")
    ax.set_title("Composer↔Validator: Score über Iterationen")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--plot", action="store_true", help="PNG erzeugen (matplotlib)")
    args = ap.parse_args(argv)

    rows = load_rows()
    if not rows:
        print(f"⚠ Keine Trial-CSVs in {TRIALS_DIR}/ gefunden. "
              f"Erst `python -m scripts.trial_compose_validate` laufen lassen.")
        return 1

    summary = summarize(rows, args.threshold)
    curves = per_iteration_means(rows)

    print("=" * 64)
    print(f"Trial-Auswertung (threshold={args.threshold})")
    print("=" * 64)
    hdr = (f"{'tag':<12} {'trials':>6} {'mean_best':>10} {'solve%':>7} "
           f"{'iter→sol':>9} {'latency':>8}")
    print(hdr)
    print("-" * len(hdr))
    for tag in sorted(summary):
        s = summary[tag]
        its = s["mean_iter_to_solve"]
        its_str = f"{its:.2f}" if its == its else "—"   # NaN-check
        print(f"{tag:<12} {s['n_trials']:>6} {s['mean_best']:>10.3f} "
              f"{s['solve_rate']*100:>6.0f}% {its_str:>9} {s['mean_latency']:>7.1f}s")

    print(ascii_plot(curves))

    # KB-Effekt explizit, falls beide Tags vorhanden
    if "with_kb" in summary and "no_kb" in summary:
        d = summary["with_kb"]["mean_best"] - summary["no_kb"]["mean_best"]
        dr = summary["with_kb"]["solve_rate"] - summary["no_kb"]["solve_rate"]
        print(f"\nKB-Effekt: Δmean_best={d:+.3f} | Δsolve_rate={dr*100:+.0f}%")
        print("→ " + ("KB hilft messbar" if d > 0.02 else
                      "kein klarer KB-Vorteil in diesem Sample"))

    if args.plot:
        png = TRIALS_DIR / "convergence.png"
        if maybe_png(curves, png):
            print(f"\n📈 Plot → {png}")
        else:
            print("\n⚠ matplotlib nicht installiert — nur ASCII-Plot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
