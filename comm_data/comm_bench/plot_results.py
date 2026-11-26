"""Wi-Fi vs 유선(eth0) 통신 벤치마크 그래프 생성.

입력: comm_bench/results/bench_wifi_r*.csv, bench_cable_r*.csv (bench_client.py 결과, 회차별)
출력: comm_bench/results/figures/*.png, comm_bench/results/summary.json (웹 페이지용)

실행: python comm_bench/plot_results.py
"""
import glob
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
FIG = os.path.join(RES, "figures")
os.makedirs(FIG, exist_ok=True)

METHODS = ["tcp", "udp", "mqtt-qos0", "mqtt-qos1", "http-keepalive", "http-new"]
SIZES = [16, 256, 1024, 8192]
SIZE_LABEL = {16: "16B", 256: "256B", 1024: "1KB", 8192: "8KB"}
ROUTES = {"wifi": "Wi-Fi", "cable": "유선 (eth0)"}

# 팔레트: 범주형 slot 1/2, 잉크/격자 (dataviz 기준 팔레트)
C = {"wifi": "#2a78d6", "cable": "#eb6834"}
INK, INK2, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

plt.rcParams.update({
    "font.family": "Malgun Gothic",
    "axes.unicode_minus": False,
    "figure.facecolor": SURF,
    "axes.facecolor": SURF,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK2,
    "axes.titlecolor": INK,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
    "savefig.dpi": 160,
    "savefig.bbox": "tight",
})


from matplotlib.ticker import FuncFormatter, LogLocator

PLAIN = FuncFormatter(lambda v, _: f"{v:,.10g}")


def plain_log(ax, axis="y"):
    """로그 축 눈금을 10^-1 대신 0.1, 1, 10 처럼 표시."""
    target = ax.yaxis if axis == "y" else ax.xaxis
    target.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
    target.set_major_formatter(PLAIN)
    target.set_minor_formatter(FuncFormatter(lambda v, _: ""))


def load():
    frames = []
    for route in ROUTES:
        files = sorted(glob.glob(os.path.join(RES, f"bench_{route}_r*.csv")))
        for f in files:
            d = pd.read_csv(f)
            d["route"] = route
            d["round"] = int(os.path.basename(f).split("_r")[-1].split(".")[0])
            frames.append(d)
    if not frames:
        raise SystemExit("bench_wifi_r*.csv / bench_cable_r*.csv 파일이 없습니다")
    df = pd.concat(frames, ignore_index=True)
    df = df[df["error"].isna() | (df["error"] == "")]
    return df


def agg(df):
    cols = ["avg_ms", "median_ms", "p95_ms", "p99_ms", "max_ms", "throughput_msg_s", "rtt_loss_pct", "throughput_loss_pct"]
    g = df.groupby(["route", "method", "size_bytes"])[cols]
    out = g.mean().add_suffix("_mean").join(g.min().add_suffix("_min")).join(g.max().add_suffix("_max"))
    out["rounds"] = df.groupby(["route", "method", "size_bytes"]).size()
    return out.reset_index()


def val(a, route, method, size, col):
    r = a[(a.route == route) & (a.method == method) & (a.size_bytes == size)]
    return float(r[col].iloc[0]) if len(r) else np.nan


def grouped_bar(a, metric, size, ylabel, title, fname, fmt):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = np.arange(len(METHODS))
    w = 0.38
    for i, route in enumerate(ROUTES):
        m = [val(a, route, k, size, f"{metric}_mean") for k in METHODS]
        lo = [val(a, route, k, size, f"{metric}_min") for k in METHODS]
        hi = [val(a, route, k, size, f"{metric}_max") for k in METHODS]
        err = [np.subtract(m, lo), np.subtract(hi, m)]
        pos = x + (i - 0.5) * (w + 0.02)
        ax.bar(pos, m, w, color=C[route], label=ROUTES[route], zorder=3)
        ax.errorbar(pos, m, yerr=err, fmt="none", ecolor=INK2, elinewidth=1, capsize=3, zorder=4)
        for p, v, h in zip(pos, m, hi):
            ax.text(p, max(v, h) * 1.08, fmt(v), ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_yscale("log")
    plain_log(ax)
    ax.set_xticks(x, METHODS)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncols=2)
    ax.margins(y=0.15)
    fig.savefig(os.path.join(FIG, fname))
    plt.close(fig)


def rtt_vs_size(a):
    fig, axes = plt.subplots(2, 3, figsize=(11, 6), sharex=True, sharey=True)
    xs = np.arange(len(SIZES))
    for ax, method in zip(axes.flat, METHODS):
        for route in ROUTES:
            m = [val(a, route, method, s, "median_ms_mean") for s in SIZES]
            lo = [val(a, route, method, s, "median_ms_min") for s in SIZES]
            hi = [val(a, route, method, s, "median_ms_max") for s in SIZES]
            ax.fill_between(xs, lo, hi, color=C[route], alpha=0.15, linewidth=0)
            ax.plot(xs, m, color=C[route], lw=2, marker="o", ms=5, label=ROUTES[route])
        ax.set_title(method, loc="left", fontsize=11)
        ax.set_yscale("log")
        plain_log(ax)
        ax.set_xticks(xs, [SIZE_LABEL[s] for s in SIZES])
    for ax in axes[:, 0]:
        ax.set_ylabel("중앙값 왕복 지연 (ms, 로그)")
    axes[0, 0].legend(loc="upper left")
    fig.suptitle("메시지 크기별 왕복 지연 (선: 회차 평균, 음영: 회차 최소~최대)", x=0.01, ha="left", fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig2_rtt_vs_size.png"))
    plt.close(fig)


def tail_latency(a, size=16):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    y = np.arange(len(METHODS))[::-1]
    for ax, route in zip(axes, ROUTES):
        med = [val(a, route, k, size, "median_ms_mean") for k in METHODS]
        p95 = [val(a, route, k, size, "p95_ms_mean") for k in METHODS]
        p99 = [val(a, route, k, size, "p99_ms_mean") for k in METHODS]
        ax.hlines(y, med, p99, color=C[route], lw=2, alpha=0.5, zorder=2)
        ax.scatter(med, y, s=60, color=C[route], zorder=3, label="중앙값")
        ax.scatter(p95, y, s=60, facecolor=SURF, edgecolor=C[route], lw=2, zorder=3, label="p95")
        ax.scatter(p99, y, s=60, marker="D", color=INK2, zorder=3, label="p99")
        for yy, v in zip(y, p99):
            ax.text(v, yy + 0.22, f"{v:.2f}", ha="center", fontsize=8, color=INK2)
        ax.set_yticks(y, METHODS)
        ax.set_xlabel("왕복 지연 (ms)")
        ax.set_title(f"{ROUTES[route]}: 지연 꼬리 (16B)", loc="left")
        ax.grid(axis="y", visible=False)
        ax.set_xlim(left=0, right=max(p99) * 1.12)
        ax.set_ylim(-0.6, len(METHODS) - 0.3)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncols=3, fontsize=9, bbox_to_anchor=(0.5, -0.06))
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig4_tail_latency_16B.png"))
    plt.close(fig)


def speedup_heatmap(a):
    mat = np.array([[val(a, "wifi", k, s, "median_ms_mean") / val(a, "cable", k, s, "median_ms_mean") for s in SIZES] for k in METHODS])
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
    fig, ax = plt.subplots(figsize=(7, 4.6))
    im = ax.imshow(mat, cmap=cmap, aspect="auto")
    ax.set_xticks(range(len(SIZES)), [SIZE_LABEL[s] for s in SIZES])
    ax.set_yticks(range(len(METHODS)), METHODS)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    vmax = np.nanmax(mat)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            ax.text(j, i, f"{v:.0f}×", ha="center", va="center", fontsize=10,
                    color="#ffffff" if v > vmax * 0.45 else INK)
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("Wi-Fi 지연 ÷ 유선 지연 (배)")
    cb.outline.set_visible(False)
    ax.set_title("유선이 Wi-Fi보다 몇 배 빠른가 (중앙값 기준)", loc="left")
    fig.savefig(os.path.join(FIG, "fig5_speedup_heatmap.png"))
    plt.close(fig)
    return mat


# 별도 측정값 (2026-11-26): iperf3 유선, 카메라 통합(가짜 영상) 로그 요약
IPERF = {"TCP 22→10": 941, "TCP 10→22": 942, "TCP 양방향(각)": 939, "UDP 1000M": 952}
FUSION = {"wifi": {"dt_ms": 97, "delay_ms": (29, 49), "pair_pct": (84, 100)},
          "cable": {"dt_ms": 30, "delay_ms": (10, 19), "pair_pct": (92, 100)}}


def extras():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [1.3, 1]})
    ax = axes[0]
    names = list(IPERF)
    vals = list(IPERF.values())
    ax.barh(names[::-1], vals[::-1], color=C["cable"], height=0.55, zorder=3)
    ax.axvline(1000, color=MUTED, ls="--", lw=1)
    ax.text(1000, len(names) - 0.4, " 1 Gbps", color=MUTED, fontsize=8, va="center")
    for i, v in enumerate(vals[::-1]):
        ax.text(v - 10, i, f"{v} Mbps", ha="right", va="center", color="#ffffff", fontsize=9, fontweight="bold")
    ax.set_xlim(0, 1080)
    ax.set_title("iperf3 유선 대역폭 (재전송 0, UDP 손실 0%)", loc="left")
    ax.grid(axis="y", visible=False)
    ax = axes[1]
    x = np.arange(2)
    w = 0.38
    for i, route in enumerate(ROUTES):
        lo, hi = FUSION[route]["delay_ms"]
        vals2 = [FUSION[route]["dt_ms"], (lo + hi) / 2]
        pos = x + (i - 0.5) * (w + 0.02)
        ax.bar(pos, vals2, w, color=C[route], label=ROUTES[route], zorder=3)
        ax.errorbar(pos[1], vals2[1], yerr=[[vals2[1] - lo], [hi - vals2[1]]], fmt="none", ecolor=INK2, capsize=3)
        ax.text(pos[0], vals2[0] + 2, f"{vals2[0]:.0f}", ha="center", fontsize=8, color=INK2)
        ax.text(pos[1], hi + 2, f"{lo}~{hi}", ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x, ["RGB-IR 짝 시각차 |dt|", "IR 도착 지연*"])
    ax.set_ylabel("ms")
    ax.set_title("카메라 통합 (가짜 영상 10fps)", loc="left")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right")
    fig.text(0.99, -0.02, "* 두 Pi 시계 차(NTP 오차) 포함", ha="right", fontsize=8, color=MUTED)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "fig6_iperf_fusion.png"))
    plt.close(fig)


def main():
    df = load()
    a = agg(df)
    rounds = {r: int(df[df.route == r]["round"].nunique()) for r in ROUTES}
    grouped_bar(a, "median_ms", 16, "중앙값 왕복 지연 (ms, 로그)",
                f"방식별 왕복 지연, 16B (막대: {rounds['wifi']}회 평균, 오차선: 최소~최대)",
                "fig1_rtt_by_method_16B.png", lambda v: f"{v:.2f}")
    rtt_vs_size(a)
    grouped_bar(a, "throughput_msg_s", 16, "초당 메시지 (Msg/s, 로그)",
                "방식별 처리량, 16B (동기 요청-응답)", "fig3_throughput_16B.png", lambda v: f"{v:,.0f}")
    tail_latency(a)
    mat = speedup_heatmap(a)
    extras()

    summary = {
        "generated": pd.Timestamp.now().isoformat(timespec="seconds"),
        "rounds": rounds,
        "methods": METHODS,
        "sizes": SIZES,
        "rows": json.loads(a.to_json(orient="records")),
        "speedup": {"methods": METHODS, "sizes": SIZES, "matrix": np.round(mat, 2).tolist()},
        "iperf": IPERF,
        "fusion": FUSION,
    }
    # 웹 대시보드용 데이터 파일
    keep = ["route", "round", "method", "size_bytes", "avg_ms", "median_ms", "p95_ms", "p99_ms", "max_ms",
            "throughput_msg_s", "rtt_loss_pct", "throughput_loss_pct"]
    out = df[keep].copy()
    for c in keep[4:]:
        out[c] = out[c].round(4)
    out.to_csv(os.path.join(RES, "bench_all.csv"), index=False)
    pd.DataFrame([
        {"test": "tcp_22_to_10", "mbps": 941, "retrans": 0, "loss_pct": "", "jitter_ms": ""},
        {"test": "tcp_10_to_22", "mbps": 942, "retrans": 0, "loss_pct": "", "jitter_ms": ""},
        {"test": "tcp_bidir_each", "mbps": 939, "retrans": 0, "loss_pct": "", "jitter_ms": ""},
        {"test": "udp_1000m", "mbps": 952, "retrans": "", "loss_pct": 0, "jitter_ms": 0.013},
    ]).to_csv(os.path.join(RES, "iperf.csv"), index=False)
    pd.DataFrame([
        {"route": r, "dt_ms": v["dt_ms"], "delay_lo_ms": v["delay_ms"][0], "delay_hi_ms": v["delay_ms"][1],
         "pair_lo_pct": v["pair_pct"][0], "pair_hi_pct": v["pair_pct"][1]} for r, v in FUSION.items()
    ]).to_csv(os.path.join(RES, "fusion.csv"), index=False)

    with open(os.path.join(RES, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("rounds:", rounds)
    print("figures:", sorted(os.listdir(FIG)))


if __name__ == "__main__":
    main()
