#!/usr/bin/env python3
"""Turn a matrix run into the paper's data pack.

Usage: python tools/matrix/emit_report.py --run full1
Writes <run>/report.md and <run>/data-pack.md (Chinese, UTF-8).
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(r"E:\Deepseek\tir-b")
OUT = ROOT / "test" / "matrix"


def load(run):
    d = OUT / run
    rows = []
    p = d / "master.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return d, rows


def by_model(rows):
    out = {}
    for r in rows:
        out.setdefault(r["model_id"], {})[r["step_id"]] = r
    return out


def fmt(v, nd=1, dash="-"):
    if v is None or v == "":
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.{nd}f}"


def table(header, lines):
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join(["---"] * len(header)) + "|"]
    out.extend(lines)
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="full1")
    args = ap.parse_args()
    d, rows = load(args.run)
    m = by_model(rows)

    spec_lines, rate_lines, power_lines, fail_lines, parity_lines = [], [], [], [], []
    for mid in sorted(m):
        s = m[mid]
        prof = s.get("profile", {})
        rate = s.get("rate_plain", {})
        mtp = s.get("rate_mtp", {})
        pw = s.get("power", {})
        spec_lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            mid, prof.get("arch", "-"), fmt((prof.get("weights_bytes") or 0) / 2**30, 2),
            prof.get("n_layer", "-"), prof.get("ctx_train", "-"),
            fmt(prof.get("kv_est_mib"), 0),
            "yes" if rate.get("status") == "ok" else "no"))
        rate_lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            mid,
            fmt(rate.get("tok_s_avg"), 1),
            fmt(mtp.get("tok_s_avg"), 1),
            fmt(mtp.get("acceptance"), 3),
            fmt(s.get("ttft_S", {}).get("ttft_ms"), 1),
            fmt(s.get("ttft_M", {}).get("ttft_ms"), 1),
            fmt(s.get("ttft_L", {}).get("ttft_ms"), 1)))
        power_lines.append("| {} | {} | {} | {} | {} | {} |".format(
            mid, fmt(pw.get("avg_power_w"), 2), fmt(pw.get("avg_sm_mhz"), 0),
            fmt(pw.get("avg_mem_mhz"), 0),
            fmt(pw.get("j_per_token_decode"), 4),
            fmt(pw.get("tokens_per_j_decode"), 3)))
        pf = s.get("test_prefill", {})
        parity_lines.append("| {} | {} | {} | {} | {} | {} |".format(
            mid,
            pf.get("prefill_parity_5", "-"), pf.get("prefill_parity_130", "-"),
            pf.get("prefill_parity_520", "-"),
            pf.get("prefill_default_match", "-"),
            pf.get("prefill_default_verdict_expected", "-")))
        for sid, r in s.items():
            if r.get("status") in ("fail", "crash", "timeout", "degenerate"):
                fail_lines.append("| {} | {} | {} | {} | {} |".format(
                    mid, sid, r.get("status"), r.get("crash_signature", "-"),
                    (r.get("error_code") if r.get("error_code") is not None else "-")))

    body = []
    body.append("# 数据包（{}）\n".format(args.run))
    body.append("行数 {}，模型 {}。表格由 `tools/matrix/emit_report.py` 直接生成，未经手工誊写。\n".format(
        len(rows), len(m)))
    body.append("## 表 A 规格\n")
    body.append(table(["模型", "arch", "权重 GiB", "层数", "ctx_train", "KV MiB", "跑通"], spec_lines))
    body.append("\n## 表 B 速率与 TTFT\n")
    body.append(table(["模型", "plain tok/s", "MTP tok/s", "acceptance",
                       "TTFT S ms", "TTFT M ms", "TTFT L ms"], rate_lines))
    body.append("\n## 表 C 能耗\n")
    body.append(table(["模型", "平均功耗 W", "SM MHz", "显存 MHz", "J/token", "tokens/J"], power_lines))
    body.append("\n## 表 D prefill parity\n")
    body.append(table(["模型", "5 tok", "130 tok", "520 tok", "default match", "预期判定"], parity_lines))
    body.append("\n## 表 E 失败与异常\n")
    body.append(table(["模型", "步骤", "状态", "签名", "错误码"], fail_lines) if fail_lines else "无\n")
    body.append("\n## 口径\n")
    body.append("- 速率：128 token，1 warmup + 3 测量，取三轮均值；ctx 16384（放不下时用实测可行档）。\n")
    body.append("- TTFT：ceiling harness，目标 128/2048/8192 token，实际 token 从 JSON 读回，prefill_batch=512。\n")
    body.append("- 能耗：200 ms 轮询，仅统计 power>20 W 的样本，J/token 按 decode 窗口折算。\n")
    body.append("- parity：test_prefill 内建三档，default 列的 `match` 是引擎默认批与显式 512 的对照。\n")

    text = "\n".join(body) + "\n"
    (d / "data-pack.md").write_text(text, encoding="utf-8")
    print("wrote", d / "data-pack.md", "rows", len(rows))


if __name__ == "__main__":
    main()
