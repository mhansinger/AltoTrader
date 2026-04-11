"""Streamlit dashboard for AltoTrader backtest results.

Shows:
  - Best SMA windows per pair (from best_windows.json)
  - Grid search heatmap (Sharpe ratio or total return)
  - Trade chart (portfolio value vs buy-and-hold) [if run_backtest writes trade logs]

Access via SSH tunnel:
    ssh -L 8501:localhost:8501 root@<hetzner-ip> -N
    → http://localhost:8501

Run locally:
    streamlit run Examples/backtest_dashboard.py --server.port 8501
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "results"))
BEST_WINDOWS_PATH = RESULTS_DIR / "best_windows.json"
REFRESH_INTERVAL_MS = 60_000  # auto-refresh every 60 s

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AltoTrader – Backtest Results",
    page_icon="📈",
    layout="wide",
)

# Auto-refresh (streamlit-autorefresh component is optional; use meta-refresh fallback)
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=REFRESH_INTERVAL_MS, key="auto_refresh")
except ImportError:
    pass  # works fine without it; user can refresh manually


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_best_windows() -> tuple[dict, str]:
    """Load best_windows.json. Returns (data_dict, updated_at_str)."""
    if not BEST_WINDOWS_PATH.exists():
        return {}, "–"
    with open(BEST_WINDOWS_PATH) as f:
        data = json.load(f)
    updated_at = data.pop("updated_at", "–")
    return data, updated_at


def load_grid_results(pair: str) -> pd.DataFrame:
    """Load the full grid search CSV for a pair."""
    slug = pair.replace("-", "")
    path = RESULTS_DIR / f"results_{slug}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def results_summary_table(best: dict) -> pd.DataFrame:
    """Convert best_windows dict → display DataFrame."""
    rows = []
    for pair, info in best.items():
        rows.append({
            "Pair":          pair,
            "Exchange":      info.get("exchange", "–"),
            "Short Window":  info.get("window_short", "–"),
            "Long Window":   info.get("window_long", "–"),
            "Sharpe Ratio":  info.get("sharpe_ratio", 0),
            "Return (%)":    info.get("total_return_pct", 0),
            "# Trades":      info.get("n_trades", 0),
            "Win Rate":      info.get("win_rate", 0),
            "Max Drawdown (%)": info.get("max_drawdown_pct", 0),
        })
    return pd.DataFrame(rows)


# ── Main dashboard ────────────────────────────────────────────────────────────

st.title("📈 AltoTrader – Backtest Results")

best, updated_at = load_best_windows()

if not best:
    st.warning(
        f"No results found in `{RESULTS_DIR}/`. "
        "Run `python Examples/run_backtest.py` first."
    )
    st.stop()

st.caption(f"Last updated: **{updated_at}** · Results dir: `{RESULTS_DIR.resolve()}`")

# ── Tab layout ────────────────────────────────────────────────────────────────

tab_overview, tab_heatmap, tab_detail = st.tabs([
    "🏆 Best Windows",
    "🗺️ Grid Search Heatmap",
    "📊 Pair Detail",
])

# ── Tab 1: Overview ───────────────────────────────────────────────────────────

with tab_overview:
    st.subheader("Best SMA Windows per Pair")
    df_summary = results_summary_table(best)

    st.dataframe(
        df_summary.style
        .background_gradient(subset=["Sharpe Ratio"], cmap="RdYlGn")
        .background_gradient(subset=["Return (%)"],   cmap="RdYlGn")
        .format({
            "Sharpe Ratio": "{:.3f}",
            "Return (%)":   "{:+.2f}%",
            "Win Rate":     "{:.1%}",
            "Max Drawdown (%)": "{:.2f}%",
        }),
        use_container_width=True,
        hide_index=True,
    )

    col1, col2, col3 = st.columns(3)
    best_sharpe_pair = df_summary.loc[df_summary["Sharpe Ratio"].idxmax(), "Pair"]
    best_return_pair = df_summary.loc[df_summary["Return (%)"].idxmax(),  "Pair"]
    col1.metric("Best Sharpe", best_sharpe_pair,
                f"{df_summary['Sharpe Ratio'].max():.3f}")
    col2.metric("Best Return", best_return_pair,
                f"{df_summary['Return (%)'].max():+.1f}%")
    col3.metric("Pairs analysed", len(df_summary))

# ── Tab 2: Grid Search Heatmap ────────────────────────────────────────────────

with tab_heatmap:
    st.subheader("Grid Search Heatmap")

    pairs = list(best.keys())
    selected_pair = st.selectbox("Select pair", pairs, key="heatmap_pair")
    metric = st.radio(
        "Colour by",
        ["sharpe_ratio", "total_return_pct", "max_drawdown_pct"],
        horizontal=True,
        format_func=lambda x: {
            "sharpe_ratio":     "Sharpe Ratio",
            "total_return_pct": "Total Return (%)",
            "max_drawdown_pct": "Max Drawdown (%)",
        }[x],
    )

    df_grid = load_grid_results(selected_pair)

    if df_grid.empty:
        st.info(f"No grid results CSV found for {selected_pair}.")
    else:
        pivot = df_grid.pivot_table(
            index="window_short",
            columns="window_long",
            values=metric,
            aggfunc="mean",
        )

        color_scale = "RdYlGn" if metric != "max_drawdown_pct" else "RdYlGn_r"
        fig = px.imshow(
            pivot,
            labels={"x": "Long Window", "y": "Short Window", "color": metric},
            title=f"{selected_pair} – {metric}",
            color_continuous_scale=color_scale,
            text_auto=".2f",
            aspect="auto",
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

        # Best combination marker
        best_row = df_grid.loc[df_grid["sharpe_ratio"].idxmax()]
        st.info(
            f"Best combo: short={int(best_row['window_short'])} / "
            f"long={int(best_row['window_long'])} | "
            f"sharpe={best_row['sharpe_ratio']:.3f} | "
            f"return={best_row['total_return_pct']:+.2f}%"
        )

        with st.expander("Full grid results table"):
            st.dataframe(
                df_grid.sort_values("sharpe_ratio", ascending=False)
                .reset_index(drop=True)
                .style.format({
                    "sharpe_ratio":     "{:.3f}",
                    "total_return_pct": "{:+.2f}%",
                    "max_drawdown_pct": "{:.2f}%",
                    "win_rate":         "{:.1%}",
                }),
                use_container_width=True,
            )

# ── Tab 3: Pair Detail ────────────────────────────────────────────────────────

with tab_detail:
    st.subheader("Pair Detail")
    selected_pair2 = st.selectbox("Select pair", pairs, key="detail_pair")
    info = best[selected_pair2]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Short Window", info.get("window_short", "–"))
    c2.metric("Long Window",  info.get("window_long",  "–"))
    c3.metric("Sharpe Ratio", f"{info.get('sharpe_ratio', 0):.3f}")
    c4.metric("Total Return", f"{info.get('total_return_pct', 0):+.2f}%")

    c5, c6, c7 = st.columns(3)
    c5.metric("# Trades",      info.get("n_trades", "–"))
    c6.metric("Win Rate",      f"{info.get('win_rate', 0):.1%}")
    c7.metric("Max Drawdown",  f"{info.get('max_drawdown_pct', 0):.2f}%")

    df_grid2 = load_grid_results(selected_pair2)
    if not df_grid2.empty:
        st.markdown("#### Return distribution across all window combinations")
        fig2 = px.histogram(
            df_grid2,
            x="total_return_pct",
            nbins=20,
            title=f"{selected_pair2} – Return distribution",
            labels={"total_return_pct": "Total Return (%)"},
            color_discrete_sequence=["#1f77b4"],
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.markdown("#### Sharpe vs. Return scatter")
        fig3 = px.scatter(
            df_grid2,
            x="total_return_pct",
            y="sharpe_ratio",
            hover_data=["window_short", "window_long", "n_trades"],
            title=f"{selected_pair2} – Sharpe vs Return",
            labels={
                "total_return_pct": "Total Return (%)",
                "sharpe_ratio":     "Sharpe Ratio",
            },
            color="n_trades",
            color_continuous_scale="Blues",
        )
        st.plotly_chart(fig3, use_container_width=True)
