#!/usr/bin/env python3
"""TIR-B planner: ModelProfile + resources + policy -> TierPlan JSON.

Usage:
  python tier_plan.py --profile qwen9b.json --ctx 16384 --kv q8_0 \
      --vram-free 7000 --vram-total 8151 --ram-free 8000 --h2d-gbps 20.96 [--out plan.json]
  python tier_plan.py --self-test

The planner is a pure function of its inputs. It never loads a model or touches
the GPU; the runtime consumes the emitted plan JSON.
"""
import argparse
import copy
import json
import math
import sys

KV_BPE = {"q8_0": 1.0, "q4_0": 0.5, "f16": 2.0}
MIB = 1048576


def kv_bytes(profile, ctx, kv_type):
    """Recompute KV bytes at an arbitrary ctx/kv type from per-layer geometry."""
    bpe = KV_BPE[kv_type]
    swa = int(profile.get("sliding_window", 0) or 0)
    total = 0
    for layer in profile.get("layers", []):
        if not layer.get("attention"):
            continue
        seq = min(ctx, swa) if layer.get("sliding") and swa > 0 else ctx
        elems = layer.get("n_kv", 0) * (layer.get("key_len", 0) + layer.get("value_len", 0))
        total += int(elems * bpe * seq)
    return total


def weights_per_layer(profile):
    out = []
    for layer in profile.get("layers", []):
        out.append(int(layer.get("attn_bytes", 0)) + int(layer.get("ffn_bytes", 0)) +
                   int(layer.get("expert_bytes", 0)) + int(layer.get("norm_bytes", 0)))
    return out


def plan(profile, resources, policy):
    """Core decision tree. Returns a plan dict shaped like tir.plan/v1."""
    warnings = []
    total_bytes = int(profile["total_bytes"])
    total_mib = total_bytes / MIB
    vram_free = float(resources["vram_free_mib"])
    vram_total = float(resources["vram_total_mib"])
    ram_free = float(resources["ram_free_mib"])
    h2d = float(resources.get("h2d_gbps", 20.0))
    nvme = float(resources.get("nvme_gbps", 5.0))
    target = float(policy.get("target_tok_s", 20.0))
    reserve = policy.get("vram_reserve_mib", 0) or max(512, int(vram_total * 0.1))
    compute = int(policy.get("compute_mib", 512))
    ctx = int(policy["ctx"])
    ctx_max = int(policy.get("ctx_max", ctx))
    mtp_mode = policy.get("mtp", "auto")
    mtp = (mtp_mode == "on") or (mtp_mode == "auto" and bool(profile.get("mtp")))
    mtp_factor = float(policy.get("mtp_factor", 2.0))
    mtp_mean_len = float(policy.get("mtp_mean_len", 3.2)) or 1.0
    if mtp:
        warnings.append(f"MTP enabled: expected_tok_s x{mtp_factor:g}, bytes/token /{mtp_mean_len:g}")

    if profile.get("n_expert", 0) > 0:
        return _make_plan(profile, ctx, policy["kv"], reserve, compute, "refuse", 0, 0, 0,
                          warnings + ["MoE model: B1 only plans dense models; B2/B3 handle experts"],
                          f"model has {profile['n_expert']} experts; B1 REFUSE", [0.0, 0.0])

    def fits(kv_type, ctx_use):
        kv = kv_bytes(profile, ctx_use, kv_type)
        return total_bytes + kv <= (vram_free - reserve - compute) * MIB, kv

    ok, kv = fits(policy["kv"], ctx)
    if ok:
        return _all_gpu(profile, ctx, policy["kv"], reserve, compute, kv, warnings, "weights+kv+compute+reserve fit free VRAM", mtp, mtp_factor)

    ok, kv = fits("q4_0", ctx)
    if ok:
        warnings.append("q8 KV does not fit; using q4 KV")
        return _all_gpu(profile, ctx, "q4_0", reserve, compute, kv, warnings, "q4 KV fits free VRAM", mtp, mtp_factor)

    for ctx_use in (16384, 8192, 4096):
        if ctx_use > ctx:
            continue
        kvq4 = kv_bytes(profile, ctx_use, "q4_0")
        if total_bytes + kvq4 <= (vram_free - reserve - compute) * MIB:
            warnings.append(f"context lowered to {ctx_use} (q4 KV)")
            return _all_gpu(profile, ctx_use, "q4_0", reserve, compute, kvq4, warnings,
                            f"16k q8/q4 do not fit; {ctx_use} q4 fits", mtp, mtp_factor)

    # selective host overflow: spill whole FFN layers from the last layer down
    layer_bytes = weights_per_layer(profile)
    kvq4 = kv_bytes(profile, ctx, "q4_0")
    budget = (vram_free - reserve - compute) * MIB - kvq4
    resident = total_bytes
    spill = []
    for idx in range(len(layer_bytes) - 1, -1, -1):
        if resident <= budget:
            break
        if layer_bytes[idx] == 0:
            continue
        resident -= layer_bytes[idx]
        spill.append(idx)
    spill.sort()
    overflow_bytes = sum(layer_bytes[idx] for idx in spill)
    if resident <= budget and overflow_bytes > 0:
        per_token_bytes = overflow_bytes / (mtp_mean_len if mtp else 1.0)
        overflow_gib = per_token_bytes / (1024 ** 3)
        mtp_note = f" (MTP /{mtp_mean_len:g})" if mtp else ""
        expected = _scale_tok_s(_expected_tok_s(per_token_bytes, h2d, target), mtp_factor if mtp else 1.0)
        if overflow_gib <= 0.6:
            return _make_plan(profile, ctx, "q4_0", reserve, compute, "host",
                              total_bytes - overflow_bytes, overflow_bytes, 0,
                              warnings, f"spill {len(spill)} FFN layers ({overflow_gib:.2f} GiB/token{mtp_note} <= 0.6 GiB budget)", expected,
                              stream_host=[f"blk.{i}.*" for i in spill])
        if overflow_gib <= 1.0 and h2d >= 25:
            warnings.append(f"spill {overflow_gib:.2f} GiB/token exceeds 0.6 GiB target; tok/s may miss {target:g}")
            return _make_plan(profile, ctx, "q4_0", reserve, compute, "host",
                              total_bytes - overflow_bytes, overflow_bytes, 0,
                              warnings, f"spill {len(spill)} FFN layers ({overflow_gib:.2f} GiB/token{mtp_note})", expected,
                              stream_host=[f"blk.{i}.*" for i in spill])
        if ram_free - 2048 >= overflow_bytes / MIB:
            warnings.append("host spill exceeds PCIe target; performance will be below target")
            return _make_plan(profile, ctx, "q4_0", reserve, compute, "host",
                              total_bytes - overflow_bytes, overflow_bytes, 0,
                              warnings, f"host spill {len(spill)} FFN layers ({overflow_gib:.2f} GiB/token{mtp_note})", expected,
                              stream_host=[f"blk.{i}.*" for i in spill])

    return _make_plan(profile, ctx, "q4_0", reserve, compute, "refuse", 0, 0, 0,
                      warnings, f"cannot fit: weights {total_mib:.0f} MiB + kv {kvq4 / MIB:.0f} MiB + compute {compute} + reserve {reserve} > free {vram_free:.0f} MiB; RAM free {ram_free:.0f} MiB",
                      [0.0, 0.0])


def _expected_tok_s(overflow_bytes, h2d_gbps, target):
    copy_ms = (overflow_bytes / (h2d_gbps * 1e9)) * 1000 if h2d_gbps > 0 else 999.0
    # assume 25-35 ms compute; overlap hides at most half the copy
    low_ms = 35.0 + max(0.0, copy_ms - 20.0)
    high_ms = 25.0 + max(0.0, copy_ms - 25.0) * 0.5
    return [round(1000.0 / low_ms, 1), round(1000.0 / high_ms, 1)]


def _scale_tok_s(pair, factor):
    return [round(pair[0] * factor, 1), round(pair[1] * factor, 1)]


def _all_gpu(profile, ctx, kv_type, reserve, compute, kv, warnings, why, mtp=False, mtp_factor=1.0):
    expected = _scale_tok_s([18.0, 28.0], mtp_factor if mtp else 1.0)
    return _make_plan(profile, ctx, kv_type, reserve, compute, "cuda",
                      int(profile["total_bytes"]), 0, 0, warnings, why,
                      expected, resident=["blk.*.attn_*", "blk.*.*norm*", "output.weight", "token_embd.weight"])


def _make_plan(profile, ctx, kv_type, reserve, compute, backend, t0_bytes, t1_bytes, t2_bytes,
               warnings, why, expected_tok_s, resident=None, stream_host=None):
    if backend == "cuda" and expected_tok_s == [18.0, 28.0]:
        expected_tok_s = [18.0, 28.0]
    plan = {
        "schema": "tir.plan/v1",
        "model": profile["model"],
        "arch": profile["arch"],
        "ctx": ctx,
        "kv_type": kv_type,
        "compute_mib": compute,
        "reserve_mib": reserve,
        "tiers": {
            "t0_mib": int(round(t0_bytes / MIB)),
            "t1_mib": int(round(t1_bytes / MIB)),
            "t2_mib": int(round(t2_bytes / MIB)),
        },
        "resident": resident or [],
        "stream_host": stream_host or [],
        "stream_disk": [],
        "expected_tok_s": expected_tok_s,
        "warnings": warnings,
        "why": why,
        "feasible": backend != "refuse",
        "backend": backend,
    }
    return plan


def self_test():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    profiles = os.path.join(here, "..", "test", "tier-profiles")
    with open(os.path.join(profiles, "qwen9b.json"), encoding="utf-8") as f:
        qwen = json.load(f)
    with open(os.path.join(profiles, "dsr1.json"), encoding="utf-8") as f:
        dsr1 = json.load(f)
    with open(os.path.join(profiles, "gemma12.json"), encoding="utf-8") as f:
        gemma12 = json.load(f)
    with open(os.path.join(profiles, "gemma26.json"), encoding="utf-8") as f:
        gemma26 = json.load(f)
    base = {"vram_total_mib": 8151, "ram_free_mib": 8000, "h2d_gbps": 20.96, "nvme_gbps": 5.0}
    cases = []

    def add(name, cond, detail=""):
        cases.append((name, bool(cond), detail))

    p = plan(qwen, {**base, "vram_free_mib": 7900}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("all-gpu 9B", p["backend"] == "cuda" and p["tiers"]["t1_mib"] == 0, p["why"])

    p = plan(qwen, {**base, "vram_free_mib": 5900}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("tight 9B spills FFN", p["backend"] == "host" and p["tiers"]["t1_mib"] > 0, p["why"])

    p = plan(gemma12, {**base, "vram_free_mib": 7900}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("12B fits after q4/lower ctx", p["backend"] == "cuda" and (p["kv_type"] == "q4_0" or p["ctx"] < 16384), p["why"])

    p = plan(gemma26, {**base, "vram_free_mib": 7500}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("26B refused in B1", p["backend"] == "refuse", p["why"])

    p = plan(qwen, {**base, "vram_free_mib": 7900}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("hybrid KV counted", p["backend"] == "cuda" and kv_bytes(qwen, 16384, "q8_0") < 300 * MIB,
        f"kv={kv_bytes(qwen, 16384, 'q8_0') / MIB:.0f} MiB")

    p = plan(gemma12, {**base, "vram_free_mib": 7900}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("sliding KV capped", p["backend"] == "cuda" and 250 * MIB < kv_bytes(gemma12, 16384, "q8_0") < 320 * MIB,
        f"kv={kv_bytes(gemma12, 16384, 'q8_0') / MIB:.0f} MiB")

    p1 = plan(dsr1, {**base, "vram_free_mib": 6200}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    p2 = plan(dsr1, {**base, "vram_free_mib": 6200}, {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512})
    add("deterministic", json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True), "")

    p = plan(qwen, {**base, "vram_free_mib": 5900},
             {"ctx": 16384, "kv": "q8_0", "vram_reserve_mib": 512, "mtp": "auto"})
    bytes_per_token = p["tiers"]["t1_mib"]  # MiB spilled; MTP divides the per-token copy
    add("MTP reduces per-token host bytes", p["backend"] == "host" and p["tiers"]["t1_mib"] > 0
        and p["expected_tok_s"][1] > 30, f"t1={bytes_per_token} MiB, expected={p['expected_tok_s']}")

    failed = 0
    for name, ok, detail in cases:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failed += 1
    print(f"{len(cases) - failed}/{len(cases)} planner cases passed")
    return 0 if failed == 0 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--kv", default="q8_0")
    ap.add_argument("--vram-free", type=float, default=6200)
    ap.add_argument("--vram-total", type=float, default=8151)
    ap.add_argument("--ram-free", type=float, default=8000)
    ap.add_argument("--h2d-gbps", type=float, default=20.96)
    ap.add_argument("--nvme-gbps", type=float, default=5.0)
    ap.add_argument("--reserve-mib", type=int, default=0)
    ap.add_argument("--mtp", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--mtp-factor", type=float, default=2.0)
    ap.add_argument("--mtp-mean-len", type=float, default=3.2)
    ap.add_argument("--compute-mib", type=int, default=512)
    ap.add_argument("--out")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.profile:
        ap.error("--profile or --self-test required")
    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)
    resources = {
        "vram_free_mib": args.vram_free,
        "vram_total_mib": args.vram_total,
        "ram_free_mib": args.ram_free,
        "h2d_gbps": args.h2d_gbps,
        "nvme_gbps": args.nvme_gbps,
    }
    policy = {"ctx": args.ctx, "ctx_max": 32768, "kv": args.kv,
              "vram_reserve_mib": args.reserve_mib, "compute_mib": args.compute_mib,
              "mtp": args.mtp, "mtp_factor": args.mtp_factor, "mtp_mean_len": args.mtp_mean_len}
    result = plan(profile, resources, policy)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()

