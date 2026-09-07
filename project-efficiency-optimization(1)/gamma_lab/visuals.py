import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

BLUE = "#285CE4"
INK = "#25334B"
MUTED = "#778296"
SURFACE = "#F3F5F9"
WHITE = "#FFFFFF"


def theme(fig, height=390):
    fig.update_layout(height=height, margin=dict(l=10, r=15, t=20, b=15), paper_bgcolor=WHITE, plot_bgcolor=WHITE, font=dict(family="Arial, sans-serif", size=14, color=INK), colorway=[BLUE, MUTED, INK], hovermode="x unified", legend=dict(orientation="h", y=1.14, x=0), xaxis_rangeslider_visible=False)
    fig.update_xaxes(showgrid=False, zeroline=False, title=None)
    fig.update_yaxes(gridcolor=SURFACE, zerolinecolor=SURFACE)
    return fig


def show(fig, key=None):
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "scrollZoom": False}, key=key)


def price_chart(bars, zone=None):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.08, row_heights=[.76, .24])
    fig.add_trace(go.Candlestick(x=bars.ts, open=bars.open, high=bars.high, low=bars.low, close=bars.close, increasing_line_color=BLUE, decreasing_line_color=MUTED, increasing_fillcolor=BLUE, decreasing_fillcolor=SURFACE, name="60s auction"), row=1, col=1)
    fig.add_trace(go.Bar(x=bars.ts, y=bars.delta, marker_color=[BLUE if d >= 0 else MUTED for d in bars.delta], name="Executed delta"), row=2, col=1)
    if zone is not None:
        fig.add_hline(y=zone, line_dash="dot", line_color=INK, annotation_text="Point-in-time concentration", row=1, col=1)
    fig.update_yaxes(title_text="Price · points", row=1, col=1)
    fig.update_yaxes(title_text="Delta", row=2, col=1)
    return theme(fig, 480)


def concentration_chart(frame):
    fig = go.Figure()
    for side, label, color in [("C", "Calls", BLUE), ("P", "Puts", MUTED)]:
        group = frame[frame.right.eq(side)]
        fig.add_trace(go.Bar(x=group.strike, y=group.gamma_dollars_1pct, name=label, marker_color=color))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Gross gamma · $ per 1% move")
    return theme(fig)


def equity_chart(results, capital):
    fig = go.Figure()
    for name, result in results.items():
        path = result["equity"]
        if not path.empty:
            points = path.iloc[::max(1, len(path) // 1600)]
            fig.add_trace(go.Scatter(x=points.ts, y=points.equity - capital, mode="lines", name=name, line=dict(width=2)))
    fig.update_yaxes(title_text="Net marked P&L · USD")
    return theme(fig, 420)


def inject_style():
    st.html('''<style>
    :root {--lab-blue:#285CE4;--lab-ink:#25334B;--lab-muted:#778296;--lab-surface:#F3F5F9;--lab-white:#FFFFFF;}
    .stApp {background:var(--lab-white);color:var(--lab-ink);}
    .stMainBlockContainer {max-width:1440px;padding-top:5rem;padding-bottom:3rem;}
    h1,h2,h3 {letter-spacing:-.035em!important;color:var(--lab-ink);}
    h1 {font-size:2.4rem!important;font-weight:600!important;}
    p {line-height:1.6;}
    [data-testid="stAlert"] {background:var(--lab-surface);color:var(--lab-ink);border:1px solid var(--lab-muted);}
    [data-testid="stAlert"] p {color:var(--lab-ink);}
    [data-testid="stCaptionContainer"] {font-size:14px;}

    [data-testid="stSidebar"] {border-right:1px solid var(--lab-surface);}
    [data-testid="stSidebar"] h2 {font-size:1.5rem;}
    [data-testid="stSidebar"] [role="radiogroup"] {gap:.3rem;}
    [data-testid="stSidebar"] [role="radiogroup"] label {border-radius:6px;padding:.5rem .7rem;}
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background:var(--lab-white);color:var(--lab-blue);}
    [data-testid="stMetric"] {padding:.7rem 0;}
    [data-testid="stMetricLabel"] {color:var(--lab-muted);font-size:14px;}
    [data-testid="stMetricValue"] {font-size:1.9rem;font-weight:500;letter-spacing:-.04em;}
    .eyebrow {font-size:14px;letter-spacing:.13em;text-transform:uppercase;color:var(--lab-muted);font-weight:600;}
    .brand {display:flex;align-items:center;gap:10px;font-size:24px;font-weight:650;letter-spacing:-1px;}
    .brand-mark {color:var(--lab-white);background:var(--lab-blue);border-radius:7px;width:34px;height:34px;display:flex;align-items:center;justify-content:center;font-size:25px;font-family:serif;}
    .brand-sub {font-size:14px;color:var(--lab-muted);padding-top:8px;}
    .workbench-bar {display:flex;align-items:center;justify-content:space-between;gap:1rem;border-bottom:1px solid var(--lab-surface);padding-bottom:1.2rem;margin-bottom:2rem;font-size:14px;color:var(--lab-muted);}
    .mode-pill {border:1px solid var(--lab-surface);border-radius:5px;padding:5px 10px;color:var(--lab-ink);}
    .empty-panel {background:var(--lab-surface);color:var(--lab-ink);border-radius:10px;padding:2rem;margin-top:1rem;margin-bottom:1rem;}
    .empty-panel h3 {font-size:1.3rem;margin:0 0 .7rem;}
    .empty-panel p {color:var(--lab-muted);margin:0;max-width:700px;font-size:16px;}
    .pipeline {display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:1.5rem 0;font-size:14px;color:var(--lab-muted);}
    .pipeline span {background:var(--lab-white);border:1px solid var(--lab-surface);border-radius:5px;padding:8px 12px;color:var(--lab-ink);}
    @media(max-width:700px){.stMainBlockContainer{padding-top:4.5rem;}h1{font-size:1.9rem!important;}.workbench-bar{flex-wrap:wrap;}.empty-panel{padding:1.5rem;}}
    </style>''')
