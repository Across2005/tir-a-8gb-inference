#!/usr/bin/env python3
"""S1 gate: profile -> compat verdict -> 128-token bench, for the local small models.

Usage: python tools/run_compat.py

Reads test/compat/models.json, writes test/compat/results.json.
Each model carries two independent verdicts:

  compat_status   PASS / WARN / REFUSE  (static, from compat_check; SKIP if the
                  profile could not be built or was built at the wrong kv)
  bench_status    OK / FAIL / SKIP      (does the runtime generate tokens)
  status          rollup: OK only when PASS + bench OK; REFUSE when refused

REFUSE is a recorded result, not a failure. Every other non-OK model fails the
gate, and the gate also fails when qwen9b MTP is below MTP_MIN_TOK_S. The last
stdout line is S1_GATE_OK / S1_GATE_BELOW_TARGET / S1_GATE_FAILED; only
S1_GATE_OK exits 0.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from compat_check import check_compat

MODELS_JSON = os.path.join(ROOT, "test", "compat", "models.json")
RESULTS_JSON = os.path.join(ROOT, "test", "compat", "results.json")
TIER_GGUF = os.path.join(HERE, "tier_gguf.py")
BENCH = os.path.join(ROOT, "build", "tir-api", "bin", "tir-bench.exe")
TEST_GENERATE = os.path.join(ROOT, "build", "tir-api", "bin", "tir-test-generate.exe")
BENCH_BIN = os.path.join(ROOT, "build", "tir-api", "bin")
CUDA_BIN = r"E:\Deepseek\tir-b\runtime\cuda-13.5\bin\x64"

CTX = 16384
KV = "q4_0"
N_PREDICT = 128
# nemotron_h emits EOG as its first sampled token on tir-bench's stock "ocean"
# prompt, so the gate pins one neutral completion prompt for all 7 models.
# tir-bench reads it from TIR_BENCH_PROMPT and falls back to its stock prompt.
BENCH_PROMPT = "The capital of France is"
VRAM_MIB = 8000
RAM_MIB = 15000
TIMEOUT_S = 1800

# MTP target model and the S1 acceptance floor for it.
MTP_MODEL = "qwen9b"
MTP_MIN_TOK_S = 65.0


def bench_env():
    env = dict(os.environ)
    env["LLAMA_DISK_STREAM_MB"] = "0"
    env["TIR_BENCH_PROMPT"] = BENCH_PROMPT
    env["PATH"] = os.pathsep.join([CUDA_BIN, BENCH_BIN, env.get("PATH", "")])
    return env


def last_json_line(text):
    """tir-bench prints its result as the last stdout line starting with '{'."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
    return None


def profile_of(path):
    proc = subprocess.run(
        [sys.executable, TIER_GGUF, path, "--ctx", str(CTX), "--kv", KV],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, timeout=TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-400:])
    return json.loads(proc.stdout)


def kv_mismatch(profile):
    """Return why the profile kv does not match the bench args, or None."""
    kv = profile.get("kv") or {}
    if kv.get("ctx") == CTX and kv.get("type") == KV:
        return None
    return f'profile kv={kv.get("ctx")}/{kv.get("type")}, bench runs {CTX}/{KV}'


def bench_error(proc):
    lines = [ln.strip() for ln in proc.stderr.splitlines() if "tir-bench:" in ln]
    if lines:
        return " | ".join(lines[-2:])[-400:]
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    return tail[-1][-400:] if tail else "no output"


def bench(path, mtp):
    proc = subprocess.run(
        [BENCH, path, str(CTX), str(mtp), str(N_PREDICT)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, env=bench_env(), timeout=TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(bench_error(proc))
    stats = last_json_line(proc.stdout)
    if stats is None:
        raise RuntimeError("no JSON line on tir-bench stdout")
    return stats


def probe_alt_prompt(path):
    """Cheap side probe: different prompt, 8 tokens, same load/decode path.

    Uses tir-test-generate, which has no prompt flag, but its hardcoded prompt
    has no sentence-final period. That is enough to separate "model cannot load
    or decode" from "this model ends the turn on a sentence-final period".
    Returns True/False, or None when the probe binary or result is missing.
    """
    if not os.path.exists(TEST_GENERATE):
        return None
    env = bench_env()
    env["TIR_TEST_MODEL"] = path
    try:
        proc = subprocess.run(
            [TEST_GENERATE], capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT, env=env, timeout=TIMEOUT_S,
        )
    except Exception:
        return None
    found = re.search(r"OK tokens=(\d+)", proc.stdout or "")
    return bool(found and int(found.group(1)) > 0)


def run_model(entry):
    name = entry["name"]
    path = entry["path"]
    mtp = int(entry.get("mtp", 0))
    known_issues = list(entry.get("known_issues") or [])
    result = {
        "name": name,
        "path": path,
        "mtp": mtp,
        "arch": None,
        "quant": None,
        "compat_status": None,
        "bench_status": None,
        "status": "FAIL",
        "reasons": [],
        "warnings": [],
        "known_issues": known_issues,
        "weights_mib": None,
        "kv_mib": None,
        "tok_s_avg": None,
        "tok_s_best": None,
        "acceptance": None,
        "mean_len": None,
        "alt_prompt_ok": None,
    }
    try:
        profile = profile_of(path)
    except Exception as exc:
        result["compat_status"] = "SKIP"
        result["bench_status"] = "SKIP"
        result["reasons"] = ["profile_failed"]
        result["error"] = str(exc)
        return result

    mismatch = kv_mismatch(profile)
    if mismatch:
        # compat would judge a different kv budget than the bench runs with
        result["compat_status"] = "SKIP"
        result["bench_status"] = "SKIP"
        result["reasons"] = ["profile_mismatch"]
        result["error"] = mismatch
        return result

    compat = check_compat(profile, requested_ctx=CTX, requested_mtp=bool(mtp),
                          vram_mib=VRAM_MIB, ram_mib=RAM_MIB)
    result.update({
        "arch": compat["arch"],
        "quant": compat["quant"],
        "compat_status": compat["status"],
        "reasons": compat["reasons"],
        "warnings": compat["warnings"],
        "weights_mib": compat["weights_mib"],
        "kv_mib": compat["kv_mib"],
    })
    if compat["status"] == "REFUSE":
        result["bench_status"] = "SKIP"
        result["status"] = "REFUSE"
        # not the 128-token bench, just proof the model still loads and decodes
        if known_issues:
            result["alt_prompt_ok"] = probe_alt_prompt(path)
        return result

    try:
        stats = bench(path, mtp)
    except Exception as exc:
        result["bench_status"] = "FAIL"
        result["error"] = str(exc)
        return result

    result.update({
        "bench_status": "OK",
        # a WARN compat verdict stays visible instead of collapsing into OK
        "status": "OK" if compat["status"] == "PASS" else "WARN",
        "tok_s_avg": stats["tok_s_avg"],
        "tok_s_best": stats["tok_s_best"],
        "acceptance": stats["acceptance"],
        "mean_len": stats["mean_len"],
    })

    if known_issues:
        result["alt_prompt_ok"] = probe_alt_prompt(path)
    return result


def evaluate_gate(results):
    """Return (gate line, detail). Only S1_GATE_OK is a pass."""
    not_ok = [f'{r["name"]}={r["status"]}' for r in results
              if r["status"] not in ("OK", "REFUSE")]
    if not_ok:
        return "S1_GATE_FAILED", "non-OK: " + ", ".join(not_ok)

    target = next((r for r in results if r["name"] == MTP_MODEL), None)
    if target is None:
        return ("S1_GATE_FAILED",
                f"{MTP_MODEL} not in models.json, cannot check {MTP_MIN_TOK_S:g} tok/s")
    if target["tok_s_avg"] is None:
        return "S1_GATE_FAILED", f'{MTP_MODEL} {target["status"]}, no throughput'
    if target["tok_s_avg"] < MTP_MIN_TOK_S:
        return ("S1_GATE_BELOW_TARGET",
                f'{MTP_MODEL} tok_s_avg {target["tok_s_avg"]:.2f} < {MTP_MIN_TOK_S:g}')
    return "S1_GATE_OK", f'{MTP_MODEL} tok_s_avg {target["tok_s_avg"]:.2f} >= {MTP_MIN_TOK_S:g}'


def main():
    if not os.path.exists(BENCH):
        print(f"run_compat: missing bench binary {BENCH}", file=sys.stderr)
        print("S1_GATE_FAILED")
        return 1
    with open(MODELS_JSON, encoding="utf-8") as f:
        spec = json.load(f)
    models = spec["models"]

    results = []
    for entry in models:
        print(f"running {entry['name']} ...", flush=True)
        results.append(run_model(entry))

    gate, detail = evaluate_gate(results)

    out = {
        "schema": "tir.compat-results/v1",
        "ctx": CTX,
        "kv": KV,
        "n_predict": N_PREDICT,
        "prompt": BENCH_PROMPT,
        "alt_prompt_probe": {
            "tool": "tir-test-generate",
            "n_predict": 8,
            "note": "hardcoded prompt without a sentence-final period; "
                    "proves load/decode only, it is not a second bench",
        },
        "vram_mib": VRAM_MIB,
        "ram_mib": RAM_MIB,
        "gate": {
            "result": gate,
            "detail": detail,
            "mtp_model": MTP_MODEL,
            "mtp_min_tok_s": MTP_MIN_TOK_S,
        },
        "models": results,
    }
    os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)
    with open(RESULTS_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")

    width = max(len(r["name"]) for r in results) + 2
    print(f"\n{'name':<{width}}{'compat':<9}{'bench':<7}{'status':<8}"
          f"{'tok_s_avg':>10}{'acceptance':>12}")
    for r in results:
        tok = f"{r['tok_s_avg']:.2f}" if r["tok_s_avg"] is not None else "-"
        acc = f"{r['acceptance']:.3f}" if r["acceptance"] is not None else "-"
        notes = ",".join(r["reasons"] + r["warnings"] + r["known_issues"])
        print(f"{r['name']:<{width}}{r['compat_status'] or '-':<9}{r['bench_status'] or '-':<7}"
              f"{r['status']:<8}{tok:>10}{acc:>12}  {notes}")

    count = {s: sum(1 for r in results if r["status"] == s)
             for s in ("OK", "WARN", "REFUSE", "FAIL")}
    print(f"\n{count['OK']}/{len(results)} OK, {count['WARN']} warn, {count['REFUSE']} refused, "
          f"{count['FAIL']} failed -> {os.path.relpath(RESULTS_JSON, ROOT)}")
    print(f"{gate}: {detail}")
    return 0 if gate == "S1_GATE_OK" else 1


if __name__ == "__main__":
    sys.exit(main())
