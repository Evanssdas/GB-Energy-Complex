"""
energy_complex.py - daily energy complex dashboard.

NOT a forecaster. This is situational awareness: what the energy complex did today,
and what the spreads that actually matter are saying. No prediction, so no baseline
to beat - it earns its place by being informative, not by being right.

Tracks: WTI, Brent, TTF (European gas), Henry Hub (US gas)
Spreads: Brent-WTI (transatlantic crude), TTF/HH ratio (transatlantic gas arb)
"""
from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pandas as pd
import yfinance as yf

LOG = "energy_complex_log.csv"
REPORT = "COMPLEX.md"

TICKERS = {
    "wti": "CL=F",      # WTI crude, USD/bbl
    "brent": "BZ=F",    # Brent crude, USD/bbl
    "ttf": "TTF=F",     # Dutch TTF gas, EUR/MWh - the European benchmark
    "hh": "NG=F",       # Henry Hub gas, USD/MMBtu - the US benchmark
}

COLS = ["date", "wti", "brent", "ttf", "hh",
        "brent_wti_spread", "ttf_hh_ratio",
        "wti_chg_pct", "brent_chg_pct", "ttf_chg_pct", "hh_chg_pct",
        "ttf_vol30_pct", "brent_vol30_pct", "status"]


def fetch_history(days: int = 400) -> pd.DataFrame:
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    frames = {}
    for name, sym in TICKERS.items():
        try:
            d = yf.download(sym, start=start, progress=False, auto_adjust=False)
            if len(d):
                s = d["Close"]
                s.index = pd.to_datetime(s.index).date
                frames[name] = s.squeeze()
                print(f"  {name:<6} {len(s):>4} rows")
            else:
                print(f"  {name:<6} NO DATA")
        except Exception as e:
            print(f"  {name:<6} failed: {type(e).__name__}")
    if not frames:
        raise RuntimeError("no market data fetched")
    df = pd.DataFrame(frames).sort_index()
    return df.ffill()          # carry the last price over holidays


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # the spreads that actually mean something
    if {"brent", "wti"}.issubset(out.columns):
        out["brent_wti_spread"] = out["brent"] - out["wti"]      # transatlantic crude premium
    if {"ttf", "hh"}.issubset(out.columns):
        out["ttf_hh_ratio"] = out["ttf"] / out["hh"]             # European gas vs US gas
    for c in ["wti", "brent", "ttf", "hh"]:
        if c in out.columns:
            out[f"{c}_chg_pct"] = out[c].pct_change() * 100
    # 30-day annualised-ish daily vol, in percent
    for c in ["ttf", "brent"]:
        if c in out.columns:
            out[f"{c}_vol30_pct"] = out[c].pct_change().rolling(30).std() * 100
    return out


def write_report(df: pd.DataFrame) -> None:
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    d = df.index[-1]
    L = []
    A = L.append

    A("# Energy Complex")
    A(f"_Auto-updated {dt.date.today().isoformat()}. Latest close: {d}. "
      "Situational awareness, not a forecast._\n")

    A("## Where the complex closed\n")
    A("| instrument | last | change | 30d vol |")
    A("|---|---:|---:|---:|")
    rows = [("WTI crude (USD/bbl)", "wti", "wti_chg_pct", None),
            ("Brent crude (USD/bbl)", "brent", "brent_chg_pct", "brent_vol30_pct"),
            ("TTF gas (EUR/MWh)", "ttf", "ttf_chg_pct", "ttf_vol30_pct"),
            ("Henry Hub gas (USD/MMBtu)", "hh", "hh_chg_pct", None)]
    for label, col, chg, vol in rows:
        if col not in df.columns:
            continue
        v = last[col]
        c = last.get(chg, np.nan)
        vv = f"{last[vol]:.1f}%" if vol and vol in df.columns and pd.notna(last.get(vol)) else "-"
        A(f"| {label} | {v:,.2f} | {c:+.2f}% | {vv} |")
    A("")

    A("## The spreads that matter\n")
    if "brent_wti_spread" in df.columns:
        s = last["brent_wti_spread"]
        A(f"**Brent - WTI: ${s:,.2f}/bbl.** The transatlantic crude premium. It widens when "
          "seaborne (Brent) supply is threatened but US (WTI) supply is not - so a widening "
          "spread is a geopolitical risk signal, not a demand signal.\n")
    if "ttf_hh_ratio" in df.columns:
        r = last["ttf_hh_ratio"]
        A(f"**TTF / Henry Hub ratio: {r:,.1f}x.** European gas costs this many times US gas "
          "(before unit conversion). The wider it goes, the stronger the pull on US LNG cargoes "
          "toward Europe. This ratio is the reason US LNG exists.\n")

    A("## Divergences worth noticing\n")
    oil_chg = last.get("brent_chg_pct", np.nan)
    gas_chg = last.get("ttf_chg_pct", np.nan)
    if pd.notna(oil_chg) and pd.notna(gas_chg):
        if oil_chg > 1.5 and gas_chg < 0:
            A("Oil is up while European gas is down. That pattern usually means a **supply-risk "
              "premium in crude** rather than a broad energy demand story - the two fuels have "
              "different chokepoints.\n")
        elif gas_chg > 3 and abs(oil_chg) < 1:
            A("European gas is moving sharply while crude is flat. That points to a **gas-specific "
              "event** - storage, LNG, or a pipeline - not a macro energy move.\n")
        elif oil_chg * gas_chg > 0 and abs(oil_chg) > 1 and abs(gas_chg) > 1:
            A("Oil and gas are moving together, which points to a **broad energy move** "
              "(macro, risk sentiment, or a shared supply shock) rather than a fuel-specific one.\n")
        else:
            A("No strong divergence today.\n")

    A("## What this is and is not\n")
    A("- This is a **daily readout**, not a forecast. Nothing here predicts tomorrow.")
    A("- Prices are settlement/close from public futures data and may differ from a trading screen.")
    A("- TTF is a futures contract and rolls; the series carries the front month.")
    A("- Weekend and holiday values are carried forward from the last close.")

    open(REPORT, "w").write("\n".join(L))
    print("wrote", REPORT)


def main() -> None:
    print("fetching energy complex...")
    hist = enrich(fetch_history())
    hist.index.name = "date"

    # append today's row to the log (idempotent on date)
    latest = hist.tail(1).reset_index()
    log = pd.read_csv(LOG) if os.path.exists(LOG) else pd.DataFrame(columns=COLS)
    latest["status"] = "ok"
    latest["date"] = latest["date"].astype(str)
    if not (log["date"].astype(str) == latest.iloc[0]["date"]).any():
        log = pd.concat([log, latest], ignore_index=True)
        print("logged", latest.iloc[0]["date"])
    else:
        # refresh the row (prices settle late)
        i = log.index[log["date"].astype(str) == latest.iloc[0]["date"]][-1]
        for c in latest.columns:
            if c in log.columns:
                log.at[i, c] = latest.iloc[0][c]
        print("refreshed", latest.iloc[0]["date"])

    keep = [c for c in COLS if c in log.columns]
    log[keep].to_csv(LOG, index=False)
    write_report(hist)


if __name__ == "__main__":
    main()
