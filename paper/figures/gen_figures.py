#!/usr/bin/env python3
"""Generate the eight SVG figures for the final report.

Only the standard library is used: each figure is hand-written SVG so the build
has no matplotlib dependency. Data for figs 4-6 is read from the matrix run when
present; the script degrades to a placeholder otherwise.
"""
import csv
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent
MATRIX_CSV = Path(r"E:\Deepseek\tir-b\test\matrix\full1\master.csv")
FONT = "Microsoft YaHei, Segoe UI, sans-serif"
INK = "#1f2328"
BLUE = "#2f6f9f"
ORANGE = "#c26a2b"
GREEN = "#3d7a4a"
GRAY = "#8a8f98"
LIGHT = "#e8edf2"
W, H = 980, 520


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def head(title, sub=""):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
        f'<text x="40" y="42" font-family="{FONT}" font-size="22" font-weight="700" fill="{INK}">{esc(title)}</text>',
    ]
    if sub:
        parts.append(f'<text x="40" y="68" font-family="{FONT}" font-size="13" fill="{GRAY}">{esc(sub)}</text>')
    return parts


def text(x, y, s, size=13, fill=INK, anchor="start", weight="400"):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')


def rect(x, y, w, h, fill=LIGHT, stroke=INK, rx=4, sw=1):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>')


def line(x1, y1, x2, y2, stroke=GRAY, sw=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{sw}"{d}/>'


def footer(parts, note):
    parts.append(line(40, H - 46, W - 40, H - 46, GRAY, 1))
    parts.append(text(40, H - 24, note, 11, GRAY))
    parts.append("</svg>")
    return "\n".join(parts)


def save(name, parts):
    body = parts if isinstance(parts, str) else "\n".join(parts)
    (OUT / f"{name}.svg").write_text(body, encoding="utf-8")


def hbar(title, sub, rows, note, unit="GB/s", color=BLUE):
    """rows: (label, value, annotation)."""
    parts = head(title, sub)
    vmax = max(r[1] for r in rows) * 1.15
    top, bar_h, gap = 110, 30, 22
    for i, (label, val, ann) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = 620 * val / vmax
        parts.append(text(40, y + 20, label, 14))
        parts.append(rect(250, y, max(w, 2), bar_h, color, color))
        parts.append(text(258 + w, y + 20, f"{val:g} {unit}  {ann}", 12, INK))
    return footer(parts, note)


# ---------------------------------------------------------------- fig 1

def fig1_log():
    """Log-scale horizontal bars, since the range spans two orders of magnitude."""
    rows = [
        ("显存 HBM 读", 330, "实测峰值；copy 306"),
        ("CPU 内存", 33.7, "DDR5 单条"),
        ("PCIe H2D", 26.7, "热态可固定内存"),
        ("E 盘顺序读", 5.56, "Gen4 x4 QD1"),
        ("E 盘写", 4.33, "Gen4 x4 QD1"),
    ]
    parts = head("图 1 本机实测有效带宽：显存、内存、PCIe 与 NVMe",
                 "对数尺度；显存比 PCIe 快约 12 倍，比 NVMe 快约 59 倍")
    lo, hi = 1.0, 500.0
    x0, x1 = 250, 900
    def sx(v):
        return x0 + (x1 - x0) * (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    for tick in (1, 10, 100, 300):
        x = sx(tick)
        parts.append(line(x, 96, x, 420, LIGHT, 1))
        parts.append(text(x, 440, f"{tick}", 11, GRAY, "middle"))
    for i, (label, val, ann) in enumerate(rows):
        y = 120 + i * 58
        parts.append(text(40, y + 22, label, 14))
        parts.append(rect(x0, y, max(sx(val) - x0, 2), 30, BLUE, BLUE))
        parts.append(text(sx(val) + 8, y + 20, f"{val:g} GB/s  {ann}", 12))
    save("fig1", footer(parts, "数据：docs/reports/2026-11-09-hardware-ceiling-probe.md §2"))


# ---------------------------------------------------------------- fig 2

def fig2():
    parts = head("图 2 开发参考的开源项目：三类关系",
                 "本地 9 个项目；8 个为无 .git 的快照，版本依据 repos.json")
    cols = [
        (40, "代码基座", GREEN, [
            ("diskinfer-windows", "fork 的直接上游\nllama.cpp 0.7.0 / ggml 0.27.0"),
            ("llama.cpp", "经 diskinfer 间接继承\n只加 ABI、tier、residency"),
        ]),
        (355, "借策略，不搬代码", BLUE, [
            ("Swiftlet", "qpack 固定 stride；Metal 不可编译"),
            ("KTransformers", "专家分桶；pinned 双缓冲"),
            ("FlexLLMGen", "Tgen/Tpre 代价式"),
            ("AirLLM", "super-block 落盘"),
            ("PowerInfer/smallthinker", "ExpertCache LRU；稀疏不适用"),
            ("Strata", "会话前缀 checkpoint"),
        ]),
        (670, "反面证据", ORANGE, [
            ("RabbitLLM", "逐层 pin 仅 0.7 GB/s"),
            ("airllm-plus", "compute 是 time.sleep"),
        ]),
    ]
    for x, title, color, items in cols:
        parts.append(rect(x, 96, 270, 30, color, color))
        parts.append(text(x + 135, 116, title, 14, "#ffffff", "middle", "700"))
        y = 138
        for name, desc in items:
            h = 54 if "\n" in desc else 44
            parts.append(rect(x, y, 270, h, "#ffffff", color))
            parts.append(text(x + 10, y + 18, name, 12, INK, weight="700"))
            for j, ln in enumerate(desc.split("\n")):
                parts.append(text(x + 10, y + 34 + j * 14, ln, 10, GRAY))
            y += h + 8
    return save("fig2", footer(parts, "来源：docs/reports/2026-11-09-tir-a2-integrated-decision.md §2/§5；low-vram-research/docs/"))


# ---------------------------------------------------------------- fig 3

def fig3():
    stages = [("P0 9B MTP", 56.93), ("A1 缓存", 74.81), ("C2e Q4+w2", 84.24),
              ("2026-11-11 门禁", 71.08)]
    parts = head("图 3 9B 的速率演进与口径变化",
                 "不同阶段测量条件不同，柱高只作趋势；最终门禁值回落到 71 附近")
    base_y, top_y = 420, 120
    bw = 120
    for i, (label, val) in enumerate(stages):
        x = 90 + i * 220
        h = (val / 100.0) * (base_y - top_y)
        parts.append(rect(x, base_y - h, bw, h, BLUE, BLUE))
        parts.append(text(x + bw / 2, base_y - h - 10, f"{val:.2f}", 13, INK, "middle", "700"))
        parts.append(text(x + bw / 2, base_y + 22, label, 12, INK, "middle"))
    parts.append(line(60, base_y, 920, base_y, INK, 1))
    for v in (0, 25, 50, 75, 100):
        y = base_y - (v / 100.0) * (base_y - top_y)
        parts.append(line(60, y, 920, y, LIGHT, 1))
        parts.append(text(45, y + 4, str(v), 10, GRAY, "end"))
    parts.append(text(30, 110, "tok/s", 11, GRAY))
    return save("fig3", footer(parts, "数据：2026-11-09-tir-a-p0-p1-technical-report.md；qwen9b-q4-mtp-w2.md；build/logs/s3b-p0-gate.raw"))


# ---------------------------------------------------------------- matrix reader

def load_rows():
    if not MATRIX_CSV.exists():
        return []
    with open(MATRIX_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rate_rows(rows, step="rate_plain"):
    out = []
    for r in rows:
        if r.get("step_id") != step or r.get("status") != "ok":
            continue
        v = fnum(r.get("tok_s_avg"))
        if v:
            out.append((r["model_id"], v))
    return sorted(out, key=lambda t: t[1], reverse=True)


# ---------------------------------------------------------------- fig 4

def fig4():
    rows = rate_rows(load_rows())
    if not rows:
        parts = head("图 4 20 模型速率全景", "矩阵尚未完成")
        return save("fig5", footer(parts, "运行 tools/matrix/run_matrix.py 后重跑本脚本"))
    parts = head("图 6 20 模型在 128 token 下的 decode 速率",
                 "ctx 16384（放不下时用实测可行档），q4 KV，greedy，同一台机器")
    vmax = max(v for _, v in rows) * 1.12
    top, gap = 100, 20
    for i, (mid, val) in enumerate(rows):
        y = top + i * gap
        w = 700 * val / vmax
        parts.append(text(40, y + 11, mid, 10))
        parts.append(rect(250, y, max(w, 2), 14, BLUE, BLUE))
        parts.append(text(256 + w, y + 11, f"{val:.1f}", 10))
    return save("fig4", footer(parts, "数据：test/matrix/full1/master.csv（rate_plain 行）"))


# ---------------------------------------------------------------- fig 5

def fig5():
    rows = load_rows()
    series = {}
    for r in rows:
        if r.get("status") != "ok" or r.get("step_id") not in ("ttft_S", "ttft_M", "ttft_L"):
            continue
        pt = fnum(r.get("prompt_tokens_actual"))
        tf = fnum(r.get("ttft_ms"))
        if pt and tf:
            series.setdefault(r["model_id"], []).append((pt, tf))
    if not series:
        parts = head("图 5 TTFT 随 prompt 长度", "矩阵尚未完成")
        return save("fig4", footer(parts, "运行矩阵后重跑本脚本"))
    parts = head("图 7 TTFT 随 prompt 长度变化", "每个点是该模型在 ceiling harness 下的三次测量中位")
    pts = [p for v in series.values() for p in v]
    xmax = max(p[0] for p in pts) * 1.05
    ymax = max(p[1] for p in pts) * 1.15
    x0, y0, x1, y1 = 90, 430, 900, 110
    for mid, vals in series.items():
        vals.sort()
        d = " ".join(f"{x0 + (px / xmax) * (x1 - x0):.1f},{y0 - (py / ymax) * (y0 - y1):.1f}"
                     for px, py in vals)
        parts.append(f'<polyline points="{d}" fill="none" stroke="{BLUE}" stroke-width="1.4" opacity="0.55"/>')
    for tick in (0, 2000, 4000, 6000, 8000):
        if tick <= xmax:
            x = x0 + (tick / xmax) * (x1 - x0)
            parts.append(text(x, y0 + 18, str(tick), 10, GRAY, "middle"))
    for tick in (0, 500, 1000, 1500, 2000, 2500):
        if tick <= ymax:
            y = y0 - (tick / ymax) * (y0 - y1)
            parts.append(line(x0, y, x1, y, LIGHT, 1))
            parts.append(text(x0 - 8, y + 4, str(tick), 10, GRAY, "end"))
    parts.append(text((x0 + x1) / 2, y0 + 38, "prompt tokens", 11, GRAY, "middle"))
    parts.append(text(30, 100, "TTFT ms", 11, GRAY))
    return save("fig5", footer(parts, "数据：test/matrix/full1/master.csv（ttft_S/M/L 行，prefill_batch=512）"))


# ---------------------------------------------------------------- fig 6

def fig6():
    rows = load_rows()
    seen = {}
    for r in rows:
        if r.get("step_id") != "profile":
            continue
        wb = fnum(r.get("weights_bytes"))
        if wb:
            seen[r["model_id"]] = wb / 2**30
    if not seen:
        parts = head("图 6 可行性地图", "矩阵尚未完成")
        return save("fig6", footer(parts, "运行矩阵后重跑本脚本"))
    parts = head("图 5 权重体积与 8 GiB 显存的关系",
                 "柱为 GGUF 文件体积；虚线为 8151 MiB 总显存，点线为 6830 MiB 可用")
    vmax = max(seen.values()) * 1.08
    top, gap = 100, 22
    for i, (mid, g) in enumerate(sorted(seen.items(), key=lambda t: t[1])):
        y = top + i * gap
        w = 700 * g / vmax
        color = GREEN if g < 5.0 else (ORANGE if g < 7.5 else "#a33")
        parts.append(text(40, y + 11, mid, 10))
        parts.append(rect(250, y, max(w, 2), 14, color, color))
        parts.append(text(256 + w, y + 11, f"{g:.2f} GiB", 10))
    for limit, label, dash in ((8151 / 1024, "总显存 8.0 GiB", "6 4"), (6830 / 1024, "可用 6.7 GiB", "2 3")):
        x = 250 + 700 * limit / vmax
        parts.append(line(x, top - 6, x, top + len(seen) * gap + 4, INK, 1.2, dash))
        parts.append(text(x + 4, top - 10, label, 10, INK))
    return save("fig6", footer(parts, "数据：master.csv profile 行（weights_bytes）与 nvidia-smi memory.total"))


# ---------------------------------------------------------------- fig 7

def fig7():
    plain = {"GPU decode (eval)": 2234.53, "sampler": 25.51, "detok": 0.59, "callback": 0.04, "host 残差": 43.41}
    mtp = {"GPU verify (prompt_eval)": 1246.95, "sampler": 21.67, "detok": 0.30, "callback": 0.03, "host 残差": 317.29}
    parts = head("图 4 128 token 的时间分解：plain 与 MTP",
                 "同一模型 qwen9b-Q4_K_M；prefill 不计入（由 TTFT 单独计）")
    colors = [BLUE, "#6b9bc3", "#9dbdd8", "#c9dbe9", ORANGE]
    for gi, (label, seg) in enumerate((("plain  总计 2304 ms", plain), ("MTP  总计 1586 ms", mtp))):
        y = 150 + gi * 130
        total = sum(seg.values())
        x = 150
        parts.append(text(40, y + 34, label, 13, INK, weight="700"))
        for i, (k, v) in enumerate(seg.items()):
            w = 700 * v / total
            parts.append(rect(x, y, max(w, 1), 46, colors[i % len(colors)], "#ffffff", 0))
            if v / total > 0.08:
                parts.append(text(x + 6, y + 28, f"{k} {v:.0f}", 10, "#ffffff"))
            x += w
    parts.append(text(40, 390, "MTP 的 verify 批记在 prompt_eval_ms，plain 的 decode 记在 eval_ms；", 11, GRAY))
    parts.append(text(40, 408, "两者用同一加法式，只是归属相反。旧版漏减 prompt_eval，才得出 91%。", 11, GRAY))
    return save("fig7", footer(parts, "数据：build/logs/d1-clean-mtp0.raw、d1-clean-mtp1.raw（最后一轮）"))


# ---------------------------------------------------------------- fig 8

def fig8():
    parts = head("图 8 失败与回退：试过、测过、放弃或保留", "每一次放弃都有实测依据，不是没有尝试")
    items = [
        ("神经元稀疏 FFN", "依赖 ReLU，Qwen 是 SwiGLU", "不做"),
        ("外挂 draft 模型", "接受率高但更慢 61.8 vs 90.5", "不做"),
        ("KV head 分段", "本机 KV 不是瓶颈", "暂缓"),
        ("Strata 整栈", "本机跑不了其模型包", "只借机制"),
        ("Rust/Go 重写引擎", "不改变 HBM 与 PCIe 下限", "不做"),
        ("默认批全局 512", "短 prompt 余量 0.42× 且真实翻转", "限定长 prompt"),
        ("前缀复用 B 路线", "探针 δ=0，零裁剪已够", "降级为 A"),
    ]
    y = 110
    for name, why, verdict in items:
        parts.append(rect(40, y, 460, 46, "#ffffff", GRAY))
        parts.append(text(54, y + 20, name, 12, INK, weight="700"))
        parts.append(text(54, y + 36, why, 10, GRAY))
        color = {"不做": ORANGE, "暂缓": GRAY, "只借机制": BLUE, "限定长 prompt": BLUE,
                 "降级为 A": GREEN}.get(verdict, BLUE)
        parts.append(rect(520, y + 6, 120, 32, color, color))
        parts.append(text(580, y + 27, verdict, 12, "#ffffff", "middle", "700"))
        y += 56
    return save("fig8", footer(parts, "来源：2026-11-09-draft-simple.md、k3-summary-9b.raw、s0-prefix-probe.raw、tir-a2-integrated-decision.md"))


def main():
    fig1_log()
    fig2()
    fig3()
    fig4()
    fig5()
    fig6()
    fig7()
    fig8()
    print("SVG written to", OUT)


if __name__ == "__main__":
    main()
