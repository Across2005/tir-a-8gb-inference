#!/usr/bin/env python3
"""Generate the 8 SVG figures for the TIR-A technical paper.

Data sources:
  fig1  docs/reports/2026-11-09-hardware-ceiling-probe.md section 2
  fig2  docs/reports/2026-11-09-tir-a-speed-history.md section 3.2
  fig3  build/logs/a4-full-{1b,4b,nemotron,8b,9b}.raw  default_batch lines
  fig4  docs/reports/2026-11-09-tir-a-speed-history.md section 4
  fig5  test/power/results.jsonl, hardware-ceiling-probe.md 2.5, tp1-gpu-load-2026-11-10.txt
  fig6  src/tir-api + CMakeLists + build-tir-api.bat
  fig7  build/run-p0-gate.bat + blueprints
  fig8  docs/reports 2026-11-09-* failure reports

Only stdlib is used. Run: python gen_figures.py
"""
import html
import os

OUT = os.path.dirname(os.path.abspath(__file__))
FONT = "Microsoft YaHei, Segoe UI, sans-serif"
INK = "#1f2328"
MUTED = "#5b6572"
GRID = "#d7dce2"
BLUE = "#2f6f9f"
BLUE2 = "#7fa8c4"
GRAY = "#aeb6bf"
ORANGE = "#d9822b"
GREEN = "#3a7d44"
RED = "#b03a2e"
AMBER = "#b8860b"


def esc(s):
    return html.escape(str(s), quote=True)


def head(w, h, title):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#5b6572"/></marker></defs>',
    ]


def text(x, y, s, size=14, anchor="start", weight="normal", fill=INK):
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" fill="{fill}">{esc(s)}</text>')


def line(x1, y1, x2, y2, color=GRID, width=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{width}"{d}/>')


def rect(x, y, w, h, fill, stroke="none", rx=3):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>'


def arrow(x1, y1, x2, y2, color=MUTED):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="1.6" marker-end="url(#a)"/>')


def footer(items):
    y = 0
    return y, items


def save(name, lines):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines + ["</svg>"]) + "\n")
    return path


def hbar_log(name, title, items, note):
    """Horizontal bars on a log10 x axis. items: (label, value, color)."""
    w, h = 1000, 460
    x0, x1 = 300, 900
    top, bottom = 96, h - 96
    lo, hi = 1.0, 1000.0
    import math

    def px(v):
        t = (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        return x0 + t * (x1 - x0)

    out = head(w, h, title)
    out.append(text(40, 74, "对数轴，单位 GB/s；数值为实测有效带宽", 13, fill=MUTED))
    for tick in (1, 10, 100, 1000):
        x = px(tick)
        out.append(line(x, top - 8, x, bottom + 8, GRID, 1))
        out.append(text(x, bottom + 28, f"{tick}", 12, anchor="middle", fill=MUTED))
    n = len(items)
    step = (bottom - top) / n
    bh = min(34, step * 0.62)
    for i, (label, value, color) in enumerate(items):
        y = top + i * step + (step - bh) / 2
        out.append(text(x0 - 14, y + bh / 2 + 5, label, 14, anchor="end"))
        x = px(value)
        out.append(rect(x0, y, max(2, x - x0), bh, color))
        out.append(text(x + 8, y + bh / 2 + 5, f"{value:g}", 13, weight="bold"))
    out.append(text(40, h - 34, note, 12, fill=MUTED))
    return save(name, out)


def nice_max(v):
    import math
    raw = v * 1.05
    mag = 10 ** int(math.floor(math.log10(raw)))
    for m in (1, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def grouped_hbar(name, title, groups, legend, note):
    """groups: (label, a_value, b_value)."""
    w, h = 1000, 520
    x0, x1 = 300, 880
    top, bottom = 100, h - 100
    maxv = nice_max(max(max(a, b) for _, a, b in groups))
    out = head(w, h, title)
    for k in range(0, 5):
        v = maxv * k / 4
        x = x0 + (v / maxv) * (x1 - x0)
        out.append(line(x, top - 8, x, bottom + 6, GRID, 1))
        out.append(text(x, bottom + 26, f"{v:.0f}", 12, anchor="middle", fill=MUTED))
    n = len(groups)
    step = (bottom - top) / n
    bh = min(18, step * 0.34)
    for i, (label, a, b) in enumerate(groups):
        y = top + i * step
        out.append(text(x0 - 14, y + step / 2 + 5, label, 14, anchor="end"))
        ya = y + step / 2 - bh - 2
        yb = y + step / 2 + 2
        wa = (a / maxv) * (x1 - x0)
        wb = (b / maxv) * (x1 - x0)
        out.append(rect(x0, ya, wa, bh, BLUE))
        out.append(rect(x0, yb, wb, bh, GRAY))
        out.append(text(x0 + wa + 6, ya + bh - 4, f"{a:g}", 11, fill=BLUE))
        out.append(text(x0 + wb + 6, yb + bh - 4, f"{b:g}", 11, fill=MUTED))
    lx = 640
    out.append(rect(lx, 70, 14, 14, BLUE))
    out.append(text(lx + 20, 82, legend[0], 13))
    out.append(rect(lx + 150, 70, 14, 14, GRAY))
    out.append(text(lx + 170, 82, legend[1], 13))
    out.append(text(40, h - 34, note, 12, fill=MUTED))
    return save(name, out)


def hbar_linear(name, title, items, note, highlight=None, value_fmt="{:.2f}"):
    """items: (label, value, color, caption)."""
    w, h = 1000, 480
    x0, x1 = 360, 860
    top, bottom = 100, h - 96
    maxv = nice_max(max(v for _, v, _, _ in items))
    out = head(w, h, title)
    n = len(items)
    step = (bottom - top) / n
    bh = min(30, step * 0.55)
    for i, (label, value, color, caption) in enumerate(items):
        y = top + i * step + (step - bh) / 2
        out.append(text(x0 - 14, y + bh / 2 + 5, label, 14, anchor="end"))
        wv = (value / maxv) * (x1 - x0)
        out.append(rect(x0, y, max(wv, 2), bh, color))
        out.append(text(x0 + wv + 8, y + bh / 2 + 5, value_fmt.format(value), 13, weight="bold"))
        if caption:
            if wv > 260:
                out.append(text(x0 + 6, y + bh / 2 + 5, caption, 11, fill="#ffffff"))
            else:
                out.append(text(x0 + wv + 74, y + bh / 2 + 5, caption, 11, fill=MUTED))
    out.append(text(40, h - 34, note, 12, fill=MUTED))
    return save(name, out)


def fig1():
    items = [
        ("HBM 纯读", 329.7, BLUE),
        ("HBM 拷贝（读+写）", 306.3, BLUE2),
        ("CPU 16 线程 memcpy", 33.7, GREEN),
        ("PCIe pinned H2D（热态）", 26.66, ORANGE),
        ("NVMe 直接 I/O（4 MiB）", 5.10, RED),
    ]
    return hbar_log("fig1.svg", "图 1  本机实测有效带宽：显存、内存、PCIe 与 NVMe",
                    items,
                    "数据：docs/reports/2026-11-09-hardware-ceiling-probe.md §2.1–§2.4；"
                    "pageable H2D 约 8.3 GB/s，未画。")


def fig2():
    groups = [
        ("1B minicpm", 336.0, 336.54),
        ("4B qwen3.5", 92.14, 93.17),
        ("Nemotron 4B", 111.05, 109.45),
        ("8B DSR1", 64.0, 64.50),
        ("9B plain", 50.84, 51.81),
        ("9B + MTP w1", 74.8, 51.81),
    ]
    return grouped_hbar("fig2.svg", "图 2  隔离复测：TIR-A 与 llama.cpp 的 decode 吞吐（tok/s）",
                        groups, ("TIR-A", "llama.cpp"),
                        "数据：docs/reports/2026-11-09-tir-a-speed-history.md §3.2；"
                        "1B 为 329–343 的中值 336，8B 为 63.7–64.3 的中值 64.0；128 gen token。")


def fig3():
    items = [
        ("1B", 29.36, BLUE, "1219.7 → 41.5 ms"),
        ("4.2B qwen3.5", 31.11, BLUE, "4943.6 → 158.9 ms"),
        ("Nemotron 4B", 30.21, BLUE, "4389.3 → 145.3 ms"),
        ("8B DSR1", 31.75, BLUE, "7788.2 → 245.3 ms"),
        ("9B（MTP，默认 2）", 1.91, ORANGE, "9168.6 → 4799.0 ms"),
    ]
    return hbar_linear("fig3.svg", "图 3  默认批 512 的 prefill 收益（逐 token / 默认，520 token）",
                       items,
                       "数据：build/logs/a4-full-{1b,4b,nemotron,8b,9b}.raw 的 default_batch 行；"
                       "9B 带 nextn，默认批按策略保持 2，因此只有 1.91×。",
                       value_fmt="{:.2f}×")


def fig4():
    w, h = 760, 340
    out = head(w, h, "图 4  MTP 上下文缓存：同一 session 重复请求的 TTFT")
    base_y, bh = 230, 56
    items = [("cold（首次请求）", 328, GRAY), ("warm（复用缓存）", 204, BLUE)]
    maxv = 360
    for i, (label, value, color) in enumerate(items):
        x = 160 + i * 260
        wv = value / maxv * 360
        out.append(rect(x, base_y - wv, 120, wv, color))
        out.append(text(x + 60, base_y + 26, label, 13, anchor="middle"))
        out.append(text(x + 60, base_y - wv - 10, f"{value} ms", 14, anchor="middle", weight="bold"))
    out.append(text(40, h - 34, "数据：docs/reports/2026-11-09-tir-a-speed-history.md §4；"
                                "收益 328→204 ms（1.61×），decode 速率不变。", 12, fill=MUTED))
    return save("fig4.svg", out)


def fig5():
    w, h = 1000, 500
    out = head(w, h, "图 5  功耗与温度：模型负载、基准与空闲")
    scenarios = [
        ("4B qwen（C3）", 85.3, 69),
        ("8B DSR1（C3）", 95.78, 74),
        ("9B MTP（tir-bench）", 98.24, 64),
        ("9B（llama-bench）", 104.65, 74),
        ("空闲（09:55 后）", 18.6, 50),
    ]
    # left panel: power
    lx0, lx1 = 300, 860
    top, bottom = 110, h - 110
    pmax = 140
    out.append(text(lx0, 82, "平均功耗（W）", 14, weight="bold"))
    n = len(scenarios)
    step = (bottom - top) / n
    bh = 24
    for i, (label, power, temp) in enumerate(scenarios):
        y = top + i * step + (step - bh) / 2
        out.append(text(lx0 - 14, y + bh / 2 + 5, label, 13, anchor="end"))
        wv = power / pmax * (lx1 - lx0)
        out.append(rect(lx0, y, wv, bh, ORANGE if i < 4 else GRAY))
        out.append(text(lx0 + wv + 8, y + bh / 2 + 5, f"{power:g} W", 12, weight="bold"))
        out.append(text(900, y + bh / 2 + 5, f"{temp} °C", 12, fill=RED))
    # 115 W limit
    xlim = lx0 + 115 / pmax * (lx1 - lx0)
    out.append(line(xlim, top - 12, xlim, bottom + 8, RED, 1.6, "6 4"))
    out.append(text(xlim - 8, top - 18, "上限 115 W", 12, anchor="end", fill=RED))
    out.append(text(40, h - 40, "数据：test/power/results.jsonl（4B/8B，decode 口径）；"
                                "hardware-ceiling-probe.md §2.5（llama-bench、tir-bench）；"
                                "build/logs/tp1-gpu-load-2026-11-10.txt（空闲）。", 11, fill=MUTED))
    out.append(text(40, h - 20, "温度是同场景采样峰值/观测值，不能当作长期热稳态。", 11, fill=MUTED))
    return save("fig5.svg", out)


def box(x, y, w, h, title, lines, fill="#f4f7fa", stroke="#9fb3c8", title_color=INK):
    out = [rect(x, y, w, h, fill, stroke, 6),
           text(x + 10, y + 22, title, 14, weight="bold", fill=title_color)]
    yy = y + 42
    for ln in lines:
        out.append(text(x + 10, yy, ln, 11.5, fill=MUTED))
        yy += 16
    return out


def fig6():
    w, h = 1040, 660
    out = head(w, h, "图 6  TIR-A 运行路径与模块边界")
    # hosts
    hosts = ["Python ctypes", "Node koffi", "C# P/Invoke", "C 测试/bench"]
    hw = 180
    for i, name in enumerate(hosts):
        x = 60 + i * 220
        out += box(x, 90, hw, 56, name, [], "#eef3f7")
        out.append(arrow(x + hw / 2, 146, x + hw / 2, 206))
    # tir.dll
    out.append(rect(40, 200, 960, 130, "#e8f0f7", "#7fa8c4", 8))
    out.append(text(56, 224, "tir.dll（C ABI，14 函数，struct_size/version 校验）", 14, weight="bold", fill=BLUE))
    mods = [
        ("tir_core", ["引擎/会话生命周期", "load / info / stats"]),
        ("tir_chat", ["model_meta", "chat_apply(_ex)"]),
        ("tir_generate", ["plain prefill", "分块 + 采样循环"]),
        ("tir_mtp", ["common_speculative", "draft context 复用"]),
    ]
    mw = 225
    for i, (name, lines) in enumerate(mods):
        x = 56 + i * 237
        out += box(x, 236, mw, 78, name, lines, "#ffffff", "#7fa8c4")
    out.append(arrow(520, 330, 520, 380))
    # llama
    out.append(rect(40, 376, 640, 90, "#f4f7fa", "#9fb3c8", 8))
    out.append(text(56, 400, "llama.dll（llama.cpp fork，master 727fa5c）", 14, weight="bold"))
    out.append(text(56, 424, "common：Jinja 模板 / speculative / 采样；llama.h C API", 11.5, fill=MUTED))
    out.append(text(56, 444, "n_batch=2048, n_ubatch=512, n_rs_seq=1, q4 KV, FA on", 11.5, fill=MUTED))
    # side: model file
    out.append(rect(740, 376, 260, 90, "#fff7e8", "#d9822b", 8))
    out.append(text(756, 400, "GGUF 模型文件（<MODEL_DIR>）", 13, weight="bold"))
    out.append(text(756, 424, "mmap；LLAMA_DISK_STREAM_MB=0", 11.5, fill=MUTED))
    out.append(text(756, 444, "1B / 4.2B / 4B / 8B / 9B", 11.5, fill=MUTED))
    out.append(arrow(740, 421, 684, 421, ORANGE))
    # ggml
    out.append(arrow(300, 466, 300, 506))
    for i, name in enumerate(["ggml-cuda.dll", "ggml-cpu.dll", "ggml-base.dll"]):
        out += box(60 + i * 250, 502, 220, 56, name, [], "#eef3f7")
    # runtime + gpu
    out.append(arrow(300, 558, 300, 596))
    out.append(rect(60, 592, 690, 52, "#f4f7fa", "#9fb3c8", 8))
    out.append(text(76, 616, "CUDA 13.5 runtime（cublas64_13 / cudart，arch 120）", 12.5, weight="bold"))
    out.append(text(76, 636, "RTX 5060 Laptop 8 GiB / HBM 306–330 GB/s / 115 W", 11.5, fill=MUTED))
    # env box
    out.append(rect(790, 490, 210, 150, "#f7f4ef", "#b8860b", 8))
    out.append(text(806, 514, "运行期开关", 13, weight="bold", fill=AMBER))
    for i, ln in enumerate(["TIR_PREFILL_BATCH", "TIR_MTP_N_MAX", "TIR_SPEC_TYPE", "TIR_DRAFT_MODEL", "LLAMA_DISK_STREAM_MB"]):
        out.append(text(806, 536 + i * 18, ln, 10.5, fill=MUTED))
    out.append(text(806, 626, "作用于 tir.dll 与 llama.dll", 10.5, fill=AMBER))
    return save("fig6.svg", out)


def fig7():
    w, h = 1040, 760
    out = head(w, h, "图 7  门禁体系：从构建到五模型矩阵")
    steps = [
        ("1  构建", ["build\\build-tir-api.bat", "MSVC + Ninja + CUDA 13.5 (arch 120)", "期望 BUILD_OK"], BLUE),
        ("2  P0 gate", ["tir-test-abi / abi-load / generate / mtp", "tir-bench 两轮（MTP on/off）→ JSON", "期望 4/4 + P0_GATE_OK"], BLUE),
        ("3  切片门", ["prefill：parity / gain / profile", "mtp：parity=64；chat / stream / compat 22", "每个切片独立 L2 + 独立验收"], BLUE),
        ("4  变异测试", ["先证明旧断言会漏（全绿）", "再证明新判据会红（def_err < 0.5·seq_err）", "RED 日志留档，恢复后 GREEN"], ORANGE),
        ("5  五模型矩阵", ["1B / 4.2B / Nemotron 4B / 8B / 9B", "520-token：cross / det / profile", "9B expect=2，其余 expect=512"], GREEN),
    ]
    y = 90
    for i, (title, lines, color) in enumerate(steps):
        out.append(rect(70, y, 760, 96, "#f7f9fb", color, 8))
        out.append(text(90, y + 28, title, 15, weight="bold", fill=color))
        for j, ln in enumerate(lines):
            out.append(text(90, y + 52 + j * 18, ln, 11.5, fill=MUTED))
        if i < len(steps) - 1:
            out.append(arrow(450, y + 96, 450, y + 120))
        y += 120
    # drift note
    out.append(rect(860, 90, 150, 216, "#fdf2f1", RED, 8))
    out.append(text(876, 116, "配置漂移", 13, weight="bold", fill=RED))
    for i, ln in enumerate(["run-p0-gate.bat", "ROOT=tir-b-p0", "与当前 tir-b", "不是同一棵树；", "2026-11-10", "发现，未修"]):
        out.append(text(876, 140 + i * 22, ln, 10.5, fill=MUTED))
    out.append(text(70, h - 30, "证据：build/build-tir-api.bat、build/run-p0-gate.bat、docs/blueprints/L2-A*.md；"
                                "门禁脚本的 ROOT 指向需与实际工作树一致。", 11, fill=MUTED))
    return save("fig7.svg", out)


def fig8():
    w, h = 1080, 700
    out = head(w, h, "图 8  失败与回退：试过、测过、放弃或保留")
    out.append(rect(370, 80, 340, 58, "#eef3f7", "#7fa8c4", 8))
    out.append(text(540, 106, "候选加速/容量路径", 15, anchor="middle", weight="bold", fill=BLUE))
    out.append(text(540, 126, "判断依据：字节、带宽、parity、功耗", 11, anchor="middle", fill=MUTED))
    items = [
        ("ngram 自投机", ["重复文本有效", "自然文本不划算"], "保留为可选", AMBER),
        ("draft-simple", ["接受率 0.83", "draft 前向太贵，4B 变慢"], "回退", RED),
        ("Q3 / 低比特", ["4B、Nemotron 更慢", "字节少不等于更快"], "回退", RED),
        ("IQ4_XS", ["不改变 4B/8B 的", "100 t/s 结论"], "不采用", RED),
        ("Q4_0 9B + MTP", ["token 38 parity 失败", "357 vs 1690"], "回退 Q4_K_M", RED),
        ("MTP width 3", ["76.9 < 84.2 t/s", "4-row verify 更贵"], "回退 width 2", RED),
        ("E 盘当内存/显存", ["直接 I/O 5.10 GB/s", "30B 约 0.43 t/s"], "只作容量层", AMBER),
        ("gemma26 专家流式", ["0.803 GB/token", "冷读 5–7 t/s"], "不进热层", AMBER),
        ("TIR-C 自研运行时", ["IR/调度/热 kernel", "无证据优于 fork"], "废止", RED),
    ]
    cols, bw, bh = 3, 320, 128
    centers = [40 + c * 350 + bw / 2 for c in range(cols)]
    out.append(line(540, 138, 540, 170, "#c7ced6", 1.4))
    out.append(line(centers[0], 170, centers[-1], 170, "#c7ced6", 1.4))
    for idx, (title, lines, verdict, color) in enumerate(items):
        r, c = divmod(idx, cols)
        x = 40 + c * 350
        y = 200 + r * 160
        out.append(rect(x, y, bw, bh, "#ffffff", color, 8))
        out.append(text(x + 14, y + 26, title, 13.5, weight="bold", fill=color))
        for j, ln in enumerate(lines):
            out.append(text(x + 14, y + 50 + j * 18, ln, 11, fill=MUTED))
        out.append(text(x + 14, y + bh - 12, "结论：" + verdict, 11.5, weight="bold", fill=color))
        if r == 0:
            out.append(arrow(x + bw / 2, 170, x + bw / 2, y - 4, "#c7ced6"))
        else:
            out.append(arrow(x + bw / 2, y - 32, x + bw / 2, y - 4, "#c7ced6"))
    out.append(text(40, h - 28, "证据：docs/reports/2026-11-09-{ngram-spec,draft-simple,4b-quant-ab,iq4xs-memory,"
                                "qwen9b-q4-mtp-w2,e-drive-feasibility,gemma26-expert-profile,tir-c-gpu-first-correction}.md；"
                                "test/power/results.jsonl。", 10.5, fill=MUTED))
    return save("fig8.svg", out)


if __name__ == "__main__":
    made = [fig1(), fig2(), fig3(), fig4(), fig5(), fig6(), fig7(), fig8()]
    for p in made:
        print(os.path.basename(p), os.path.getsize(p))
