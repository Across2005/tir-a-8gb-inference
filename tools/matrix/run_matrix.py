#!/usr/bin/env python3
"""TIR-A full model matrix driver (schema tir.matrix/v1).

Reads tools/matrix/models.json and runs the per-model step ladder against tir.dll,
writing everything under test/matrix/<run_id>/.

Examples:
  python tools/matrix/run_matrix.py --dry-run
  python tools/matrix/run_matrix.py --models minicpm5-1b
  python tools/matrix/run_matrix.py --resume
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"E:\Deepseek\tir-b")
BIN = ROOT / "build" / "tir-api" / "bin"
CUDA_X64 = ROOT / "runtime" / "cuda-13.5" / "bin" / "x64"
CUDA_BIN = ROOT / "runtime" / "cuda-13.5" / "bin"
TOOLS = ROOT / "tools"
HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "models.json"
OUT_ROOT = ROOT / "test" / "matrix"
FORBIDDEN_PATH = ("llama-b12202",)
BENCH_PROMPT = "The capital of France is"
ROOF_GBPS = 330.0
TZ = timezone(timedelta(hours=8))

BENCH = "tir-bench.exe"
CEILING = "tir-bench-ceiling.exe"
T_PROFILE = "tir-test-profile.exe"
T_PREFILL = "tir-test-prefill.exe"
T_MTP = "tir-test-mtp.exe"

SCHEMA = "tir.matrix/v1"


# --------------------------------------------------------------------------- util

def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def run_id_new() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%dT%H-%M-%S")


def atomic_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def sha256_16(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def decode(b: bytes) -> str:
    return b.decode("utf-8", "replace")


# --------------------------------------------------------------------------- gpu

GPU_Q = ("memory.total,memory.used,memory.free,utilization.gpu,power.draw,"
         "temperature.gpu,clocks.sm,clocks.mem")


def smi(query: str = GPU_Q) -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, timeout=10)
        if out.returncode != 0:
            return {}
        vals = decode(out.stdout).strip().splitlines()[0].split(",")
        keys = query.split(",")
        d = {}
        for k, v in zip(keys, vals):
            v = v.strip()
            try:
                d[k] = float(v)
            except ValueError:
                d[k] = v
        return d
    except Exception:
        return {}


def compute_apps() -> list:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader"],
            capture_output=True, timeout=10)
        rows = []
        for line in decode(out.stdout).splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            rows.append({"pid": parts[0], "name": parts[1] if len(parts) > 1 else ""})
        return rows
    except Exception:
        return []


COMPUTE_NAME = re.compile(
    r"(python|tir-|llama|ggml|torch|vllm|sglang|ollama|lmstudio|node\.exe)",
    re.IGNORECASE)


def gpu_gate(min_free_mib: float = 800.0, own_pids=()) -> dict:
    g = smi()
    if not g or "memory.free" not in g:
        return {"ok": False, "reason": "nvidia-smi_unavailable"}
    if g["memory.free"] < min_free_mib:
        return {"ok": False, "reason": f"free_{g['memory.free']:.0f}MiB<{min_free_mib:.0f}"}
    # WDDM lists every graphics process here, so only real compute binaries count
    apps = [a for a in compute_apps()
            if a["pid"] not in own_pids and COMPUTE_NAME.search(a["name"])]
    if apps:
        return {"ok": False, "reason": "foreign_compute_apps",
                "apps": [a["name"] for a in apps][:5]}
    return {"ok": True, "reason": "", "state": g}


def wait_cooldown(target_temp_c: float = 60.0, max_wait_s: float = 90.0) -> dict:
    t0 = time.time()
    reached = None
    while time.time() - t0 < max_wait_s:
        g = smi("temperature.gpu")
        reached = g.get("temperature.gpu")
        if reached is None or reached <= target_temp_c:
            break
        time.sleep(5)
    return {"cooldown_s": round(time.time() - t0, 1), "cooldown_temp_c": reached}


class Poller(threading.Thread):
    def __init__(self, out_csv: Path, interval: float = 0.2):
        super().__init__(daemon=True)
        self.out_csv = out_csv
        self.interval = interval
        self.stop_flag = threading.Event()
        self.samples = []
        self.peak_used = 0.0
        self.min_mem_mhz = None
        self.max_temp = None
        self.active = 0

    def run(self):
        with open(self.out_csv, "w", encoding="utf-8", newline="\n") as f:
            f.write("t_rel,sm_mhz,mem_mhz,power_w,temp_c,used_mib,util\n")
            t0 = time.time()
            while not self.stop_flag.is_set():
                g = smi(GPU_Q)
                if g:
                    row = (round(time.time() - t0, 2), g.get("clocks.sm"),
                           g.get("clocks.mem"), g.get("power.draw"),
                           g.get("temperature.gpu"), g.get("memory.used"),
                           g.get("utilization.gpu"))
                    self.samples.append(row)
                    f.write(",".join("" if v is None else str(v) for v in row) + "\n")
                    f.flush()
                    used = g.get("memory.used") or 0
                    self.peak_used = max(self.peak_used, used)
                    mm = g.get("clocks.mem")
                    if isinstance(mm, float):
                        self.min_mem_mhz = mm if self.min_mem_mhz is None else min(self.min_mem_mhz, mm)
                    tp = g.get("temperature.gpu")
                    if isinstance(tp, float):
                        self.max_temp = tp if self.max_temp is None else max(self.max_temp, tp)
                    pw = g.get("power.draw")
                    if isinstance(pw, float) and pw > 20.0:
                        self.active += 1
                time.sleep(self.interval)

    def stop(self):
        self.stop_flag.set()
        self.join(timeout=5)


# --------------------------------------------------------------------------- env / exec

def build_env(model_path: str, *, prefill: str | None = None,
              spec_debug: bool = False, test_model: bool = False) -> dict:
    segs = [str(CUDA_X64), str(CUDA_BIN), str(BIN)]
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if not p:
            continue
        low = p.lower()
        if any(f in low for f in FORBIDDEN_PATH):
            continue
        segs.append(p)
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(segs)
    env["LLAMA_DISK_STREAM_MB"] = "0"
    env["TIR_BENCH_PROMPT"] = BENCH_PROMPT
    env["TIR_MTP_N_MAX"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("TIR_SPEC_TYPE", None)
    env.pop("TIR_DRAFT_MODEL", None)
    if prefill is None:
        env.pop("TIR_PREFILL_BATCH", None)
    else:
        env["TIR_PREFILL_BATCH"] = str(prefill)
    if spec_debug:
        env["TIR_SPEC_DEBUG"] = "1"
    else:
        env.pop("TIR_SPEC_DEBUG", None)
    if test_model:
        env["TIR_TEST_MODEL"] = model_path
    else:
        env.pop("TIR_TEST_MODEL", None)
    return env


ERR_MAP = {
    "illegal memory access": "illegal_memory_access",
    "cudaErrorDevicesUnavailable": "device_unavailable",
    "out of memory": "vram_oom",
    "cudaMalloc": "vram_oom",
    "failed to allocate": "vram_oom",
    "Assertion failed": "assert_abort",
    "n_ctx exceeds the model training length": "ctx_exceeds_train",
    "no throughput": "degenerate_eog",
    "llama_model_load_from_file failed": "load_failed",
    "llama_init_from_model failed": "context_init_failed",
}


def classify(rc, stderr: str, stdout: str) -> tuple:
    """Return (status, crash_signature, error_code)."""
    blob = (stderr or "") + "\n" + (stdout or "")
    sig = None
    for needle, name in ERR_MAP.items():
        if needle in blob:
            sig = name
            break
    if rc is not None and rc < 0:
        code = rc + (1 << 32)
        if code == 0xC0000135:
            return "crash", "dll_not_found", None
        if code == 0xC0000005:
            return "crash", "access_violation", None
        return "crash", sig or f"exit_{code:#x}", None
    m = re.search(r"n_ctx exceeds the model training length", blob)
    if m:
        return "fail", "ctx_exceeds_train", 1
    if sig in ("illegal_memory_access", "device_unavailable", "access_violation"):
        return "crash", sig, None
    if sig == "assert_abort":
        return "crash", sig, None
    if sig == "degenerate_eog":
        return "degenerate", sig, None
    if rc == 2 and ("usage:" in blob or "bad arguments" in blob):
        return "fail", "bad_args", 1
    if rc == 0:
        return "ok", sig, 0
    return "fail", sig, None


class Step:
    def __init__(self, step_id, argv, *, timeout=1200, env=None, kind="exe",
                 gpu=True, retry=0):
        self.step_id = step_id
        self.argv = argv
        self.timeout = timeout
        self.env = env or {}
        self.kind = kind
        self.gpu = gpu
        self.retry = retry


def run_step(step: Step, run_dir: Path, model_id: str, base_env: dict,
             *, force_gpu_gate=True) -> dict:
    raw_dir = run_dir / "raw" / model_id
    gpu_dir = run_dir / "gpu" / model_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    gpu_dir.mkdir(parents=True, exist_ok=True)
    so = raw_dir / f"{step.step_id}.stdout.log"
    se = raw_dir / f"{step.step_id}.stderr.log"
    poll_csv = gpu_dir / f"{step.step_id}.poll.csv"

    if step.gpu and force_gpu_gate:
        gate = gpu_gate()
        if not gate["ok"]:
            return {
                "step_id": step.step_id, "status": "skip",
                "skip_reason": "gpu_gate:" + gate["reason"],
                "exit_code": None, "wall_s": 0.0, "stdout": "", "stderr": "",
                "crash_signature": None, "error_code": None,
                "raw_stdout": str(so), "raw_stderr": str(se), "poll_csv": None,
                "vram_peak_mib": None, "vram_before_mib": None, "vram_after_mib": None,
                "gpu_before": {}, "gpu_after": {}, "poll_samples": 0, "poll_active": 0,
                "min_mem_mhz": None, "max_temp_c": None,
            }

    before = smi() if step.gpu else {}
    poller = Poller(poll_csv) if step.gpu else None
    if poller:
        poller.start()

    env = dict(base_env)
    env.update(step.env)
    t0 = time.time()
    proc = None
    rc = None
    out_b = b""
    err_b = b""
    timed_out = False
    try:
        if step.kind == "powershell":
            argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File"] + step.argv
        else:
            argv = step.argv
        proc = subprocess.Popen(argv, cwd=str(BIN), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        try:
            out_b, err_b = proc.communicate(timeout=step.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=30)
            except Exception:
                pass
            try:
                out_b, err_b = proc.communicate(timeout=30)
            except Exception:
                pass
        rc = proc.returncode
    except FileNotFoundError as exc:
        err_b = str(exc).encode()
        rc = None
    finally:
        if poller:
            poller.stop()
        so.write_bytes(out_b or b"")
        se.write_bytes(err_b or b"")

    after = smi() if step.gpu else {}
    stdout = decode(out_b or b"")
    stderr = decode(err_b or b"")

    if timed_out:
        status, sig, ecode = "timeout", "timeout", None
    elif rc is None:
        status, sig, ecode = "crash", "process_start_failed", None
    else:
        status, sig, ecode = classify(rc, stderr, stdout)

    return {
        "step_id": step.step_id,
        "status": status,
        "skip_reason": None,
        "exit_code": rc,
        "wall_s": round(time.time() - t0, 2),
        "stdout": stdout,
        "stderr": stderr,
        "crash_signature": sig,
        "error_code": ecode,
        "raw_stdout": str(so),
        "raw_stderr": str(se),
        "poll_csv": str(poll_csv) if poller else None,
        "vram_peak_mib": poller.peak_used if poller and poller.peak_used else None,
        "vram_before_mib": before.get("memory.used"),
        "vram_after_mib": after.get("memory.used"),
        "gpu_before": before,
        "gpu_after": after,
        "poll_samples": len(poller.samples) if poller else 0,
        "poll_active": poller.active if poller else 0,
        "min_mem_mhz": poller.min_mem_mhz if poller else None,
        "max_temp_c": poller.max_temp if poller else None,
    }


# --------------------------------------------------------------------------- parsers

RE_RUN = re.compile(
    r"^tir-bench: run tokens=(?P<tokens>\d+) bytes=(?P<bytes>\d+) "
    r"prompt_tokens=(?P<prompt_tokens>\d+) gen_tokens=(?P<gen_tokens>\d+) "
    r"ttft_ms=(?P<ttft_ms>[\d.]+) decode_ms=(?P<decode_ms>[\d.]+) "
    r"tok_s=(?P<tok_s>[\d.]+) acceptance=(?P<acceptance>[\d.]+) "
    r"mean_len=(?P<mean_len>[\d.]+) eval_ms=(?P<eval_ms>[\d.]+) "
    r"prompt_eval_ms=(?P<prompt_eval_ms>[\d.]+) sampler_ms=(?P<sampler_ms>[\d.]+) "
    r"step_us=(?P<step_us>\d+) detok_us=(?P<detok_us>\d+) "
    r"callback_us=(?P<callback_us>\d+) graph_reused=(?P<graph_reused>-?\d+) "
    r"graph_reallocs_same=(?P<grs>-?\d+) graph_reallocs_diff=(?P<grd>-?\d+)",
    re.M)

RE_BUF = {
    "cuda_model_mib": r"CUDA0 model buffer size\s*=\s*([\d.]+) MiB",
    "cpu_mapped_mib": r"CPU_Mapped model buffer size\s*=\s*([\d.]+) MiB",
    "cuda_kv_mib": r"CUDA0 KV buffer size\s*=\s*([\d.]+) MiB",
    "cuda_compute_mib": r"CUDA0 compute buffer size\s*=\s*([\d.]+) MiB",
    "host_compute_mib": r"CUDA_Host compute buffer size\s*=\s*([\d.]+) MiB",
}
RE_OFFLOAD = re.compile(r"offloaded (\d+/\d+) layers to GPU")
RE_SPEC = re.compile(r"tir-spec: drafted=(\d+) accepted=(\d+) steps=(\d+) gen=(\d+) n_max=(\d+)")
RE_DRAFT = re.compile(r"tir-spec: draft eval_ms=([\d.]+) p_eval_ms=([\d.]+) n_eval=(\d+)")


def last_json(text: str):
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def parse_buffers(stderr: str) -> dict:
    out = {}
    for k, pat in RE_BUF.items():
        m = re.search(pat, stderr)
        if m:
            out[k] = float(m.group(1))
    m = RE_OFFLOAD.search(stderr)
    if m:
        out["offloaded"] = m.group(1)
    return out


def parse_bench(stdout: str, stderr: str) -> dict:
    head = last_json(stdout) or {}
    runs = []
    for m in RE_RUN.finditer(stderr):
        d = {}
        for k, v in m.groupdict().items():
            d[k] = float(v) if ("." in v) else int(v)
        runs.append(d)
    sp = RE_SPEC.search(stderr)
    dr = RE_DRAFT.search(stderr)
    return {
        "headline": head,
        "runs": runs,
        "buffers": parse_buffers(stderr),
        "spec_steps": int(sp.group(3)) if sp else None,
        "spec_drafted": int(sp.group(1)) if sp else None,
        "spec_accepted": int(sp.group(2)) if sp else None,
        "spec_n_max": int(sp.group(5)) if sp else None,
        "draft_eval_ms": float(dr.group(1)) if dr else None,
        "draft_p_eval_ms": float(dr.group(2)) if dr else None,
        "draft_n_eval": int(dr.group(3)) if dr else None,
        "runs_consistent": bool(runs) and head.get("gen_tokens") == runs[-1].get("gen_tokens"),
    }


def parse_ceiling(stdout: str, stderr: str) -> dict:
    j = last_json(stdout) or {}
    j["buffers"] = parse_buffers(stderr)
    return j


def parse_prefill(stdout: str) -> dict:
    d = {"overall": None}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("prompt_tokens="):
            m = re.search(r"prompt_tokens=(\d+) seq_runs=[\d./]+ batch_runs=[\d./]+ "
                          r"seq_med=([\d.]+) batch_med=([\d.]+) parity=(\w+)", line)
            if m:
                d.setdefault("cases", []).append(
                    {"prompt_tokens": int(m.group(1)), "seq_med": float(m.group(2)),
                     "batch_med": float(m.group(3)), "parity": m.group(4)})
        elif line.startswith("high_batch "):
            m = re.search(r"prompt_tokens=(\d+).*gain=([\d.]+)x cross=(\w+) det=(\w+)", line)
            if m:
                d["high"] = {"prompt_tokens": int(m.group(1)), "gain": float(m.group(2)),
                             "cross": m.group(3), "det": m.group(4)}
        elif line.startswith("default_batch "):
            m = re.search(r"expect=(\d+) prompt_tokens=(\d+).*gain=([\d.]+) "
                          r"profile=([\d.]+) def_err=([\d.]+) seq_err=([\d.]+) "
                          r"match=(\w+) parity=(\w+) profile_match=(\w+)", line)
            if m:
                d["default"] = {"expect": int(m.group(1)), "prompt_tokens": int(m.group(2)),
                                "gain": float(m.group(3)), "profile": float(m.group(4)),
                                "match": m.group(7), "parity": m.group(8),
                                "profile_match": m.group(9)}
        elif line.startswith("cancel_after="):
            d["cancel"] = line
        elif line.startswith("reuse "):
            d["reuse"] = line
        elif line.startswith("env="):
            d.setdefault("env_fallbacks", []).append(line)
        elif line.startswith("test_prefill: "):
            d["overall"] = line.split(":", 1)[1].strip()
    return d


def parse_mtp(stdout: str) -> dict:
    d = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("mtp acceptance="):
            d["mtp_line"] = line
        elif line.startswith("test_mtp: OK"):
            m = re.search(r"plain=(\d+) mtp=(\d+) parity=(\d+)", line)
            if m:
                d.update({"plain_tokens": int(m.group(1)), "mtp_tokens": int(m.group(2)),
                          "parity_tokens": int(m.group(3))})
        elif line.startswith("mismatch at"):
            m = re.search(r"at (\d+)", line)
            if m:
                d["first_divergence"] = int(m.group(1))
        elif line.startswith("cache cold_ms="):
            m = re.search(r"cold_ms=([\d.]+) warm_ms=([\d.]+)", line)
            if m:
                d["cache_cold_ms"] = float(m.group(1))
                d["cache_warm_ms"] = float(m.group(2))
        elif line.startswith("cancel: tokens_before_cancel="):
            m = re.search(r"=(\d+)", line)
            if m:
                d["cancel_tokens"] = int(m.group(1))
        elif line.startswith("cancel: tokens_after_reuse="):
            m = re.search(r"=(\d+)", line)
            if m:
                d["reuse_tokens"] = int(m.group(1))
        elif line.startswith("oversize_mtp:"):
            m = re.search(r"=(\d+)", line)
            if m:
                d["oversize_reject_tokens"] = int(m.group(1))
    return d


def parse_profile(stdout: str) -> dict:
    d = {}
    for line in stdout.splitlines():
        if "test_profile: OK" in line:
            m = re.search(r"tokens=(\d+) eval_ms=([\d.]+).*?step_us=(\d+)", line)
            if m:
                d.update({"tokens": int(m.group(1)), "eval_ms": float(m.group(2)),
                          "step_us": int(m.group(3))})
        if line.strip().startswith("ids:"):
            d["ids_sha256"] = hashlib.sha256(line.encode()).hexdigest()[:16]
    d["ok"] = "test_profile: OK" in stdout
    return d


def parse_power(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return {}


# --------------------------------------------------------------------------- analysis

def roofline_ledger(row: dict) -> dict:
    """Fill host residual, bandwidth and roofline fields. Never clamps silently."""
    out = {}
    step_ms = (row.get("step_us") or 0) / 1000.0
    ev = row.get("eval_ms") or 0.0
    pe = row.get("prompt_eval_ms") or 0.0
    sm = row.get("sampler_ms") or 0.0
    det = (row.get("detok_us") or 0) / 1000.0
    cb = (row.get("callback_us") or 0) / 1000.0
    if step_ms > 0:
        host = step_ms - ev - pe - sm - det - cb
        out["host_residual_ms"] = round(host, 3)
        out["host_residual_pct"] = round(host / step_ms * 100, 2)
        dec = row.get("decode_ms") or 0.0
        if dec > 0:
            out["step_decode_delta_pct"] = round(abs(step_ms - dec) / dec * 100, 2)
    out["perf_valid"] = bool(ev > 0 or pe > 0)
    wg = (row.get("weights_bytes") or 0) / 1e9
    gen = row.get("gen_tokens") or 0
    if row.get("mtp_effective"):
        steps = row.get("spec_steps")
        ttft = row.get("ttft_ms") or 0.0
        prefill = min(ttft, pe) if pe else 0.0
        verify = pe - prefill
        if steps and verify > 0 and wg > 0:
            bw = wg / ((verify / steps) / 1000.0)
            out["bw_eff_gbps"] = round(bw, 1)
            out["bw_basis"] = "mtp_verify"
            out["bw_valid"] = bw <= ROOF_GBPS * 1.05
        else:
            out["bw_basis"] = "mtp_verify"
            out["bw_valid"] = False
    else:
        if ev > 0 and gen > 0 and wg > 0:
            bw = wg * gen * 1000.0 / ev
            out["bw_eff_gbps"] = round(bw, 1)
            out["bw_basis"] = "plain_eval"
            out["bw_valid"] = bw <= ROOF_GBPS * 1.05
        else:
            out["bw_basis"] = "plain_eval"
            out["bw_valid"] = False
    return out


def roof_max(weights_gb: float, kv_gb: float = 0.0) -> dict:
    if weights_gb <= 0:
        return {}
    short_ms = weights_gb / ROOF_GBPS * 1000.0
    full_ms = (weights_gb + kv_gb) / ROOF_GBPS * 1000.0
    return {"roof_max_short_tok_s": round(1000.0 / short_ms, 2),
            "roof_max_full_tok_s": round(1000.0 / full_ms, 2)}


# --------------------------------------------------------------------------- schema

COLS = [
    "schema", "row_id", "run_id", "model_id", "model_path", "model_source",
    "model_bytes", "step_id", "seq", "status", "skip_reason", "fail_stage",
    "error_code", "crash_signature", "exit_code", "wall_s",
    "started_at", "raw_stdout", "raw_stderr", "poll_csv",
    "build_id", "tir_dll_sha256", "git_head", "git_dirty_count", "path_head",
    "tool_argv",
    "ctx", "ctx_requested", "ctx_clamp_reason", "kv_q4", "mtp", "mtp_effective",
    "mtp_n_max", "prefill_batch", "prefill_batch_source", "n_predict", "runs",
    "prompt_id", "prompt_tokens_target", "prompt_tokens_actual", "spec_debug",
    "arch", "n_layer", "n_trunk_layers", "nextn_layers", "n_embd", "n_expert",
    "ctx_train", "hybrid_ssm", "sliding_window", "weights_bytes", "kv_est_mib",
    "tok_s_avg", "tok_s_best", "tok_s_p50", "tok_s_p95", "tok_s_min", "tok_s_max",
    "gen_tokens", "ttft_ms", "decode_ms", "acceptance", "mean_len",
    "spec_steps", "spec_drafted", "spec_accepted", "spec_n_max",
    "draft_eval_ms", "draft_p_eval_ms", "draft_n_eval",
    "eval_ms", "prompt_eval_ms", "sampler_ms", "step_us", "detok_us", "callback_us",
    "graph_reused", "graph_reallocs_same", "graph_reallocs_diff", "perf_valid",
    "runs_consistent",
    "host_residual_ms", "host_residual_pct", "step_decode_delta_pct",
    "bw_eff_gbps", "bw_basis", "bw_valid", "roof_max_short_tok_s", "roof_max_full_tok_s",
    "roofline_eff",
    "cuda_model_mib", "cpu_mapped_mib", "cuda_kv_mib", "cuda_compute_mib",
    "host_compute_mib", "offloaded",
    "vram_before_mib", "vram_peak_mib", "vram_after_mib",
    "gpu_before_sm_mhz", "gpu_before_mem_mhz", "gpu_before_temp_c", "gpu_before_power_w",
    "gpu_after_sm_mhz", "gpu_after_mem_mhz", "gpu_after_temp_c", "gpu_after_power_w",
    "cooldown_s", "cooldown_temp_c",
    "avg_power_w", "avg_sm_mhz", "avg_mem_mhz", "min_mem_mhz", "max_temp_c",
    "j_per_token_decode", "tokens_per_j_decode", "power_samples",
    "prefill_overall", "prefill_parity_5", "prefill_parity_130", "prefill_parity_520",
    "prefill_default_expect", "prefill_default_match", "prefill_default_parity",
    "prefill_default_verdict_expected",
    "mtp_parity_tokens", "mtp_first_divergence", "mtp_cache_cold_ms", "mtp_cache_warm_ms",
    "mtp_cancel_tokens", "mtp_reuse_tokens", "mtp_oversize_reject_tokens",
]


def blank_row(run_id: str, model: dict, step_id: str) -> dict:
    return {"schema": SCHEMA, "run_id": run_id, "model_id": model["id"],
            "model_path": model["path"], "model_source": model.get("source", ""),
            "model_bytes": model.get("bytes"), "step_id": step_id}


def append_row(run_dir: Path, row: dict) -> None:
    with open(run_dir / "master.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(run_dir: Path) -> int:
    src = run_dir / "master.jsonl"
    if not src.exists():
        return 0
    latest = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            latest[(r.get("model_id"), r.get("step_id"))] = r
    rows = list(latest.values())
    with open(run_dir / "master.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLS})
    return len(rows)


# --------------------------------------------------------------------------- steps

def spec_step(model: dict) -> Step:
    return Step("profile", [sys.executable, str(TOOLS / "tier_gguf.py"),
                            model["path"], "--ctx", "16384", "--kv", "q4_0"],
                timeout=180, gpu=False)


def bench_step(step_id: str, model: dict, ctx: int, mtp: int, n_predict: int,
               *, spec_debug=False, prefill=None, timeout=None):
    if timeout is None:
        timeout = 300 + n_predict * 4
    env = build_env(model["path"], prefill=prefill, spec_debug=spec_debug)  # rebuilt per step
    return Step(step_id, [str(BIN / BENCH), model["path"], str(ctx), str(mtp), str(n_predict)],
                timeout=timeout, gpu=True), env


def ceiling_step(step_id: str, model: dict, ctx: int, target: int, warmup: int = 512):
    return Step(step_id, [str(BIN / CEILING), model["path"], str(ctx), str(target),
                          "128", "1", "3", str(warmup)], timeout=1800, gpu=True), \
        build_env(model["path"], prefill="512")


def power_step(model: dict, ctx: int, run_dir: Path):
    out = run_dir / "raw" / model["id"] / "power.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    return Step("power", [str(ROOT / "test" / "bench-power.ps1"),
                          "-Model", model["path"], "-Ctx", str(ctx),
                          "-PromptTokens", "128", "-NPredict", "512", "-Runs", "1",
                          "-KvQ4", "1", "-Label", f"{model['id']}:{ctx}",
                          "-Out", str(out)], kind="powershell", timeout=900, gpu=True), \
        build_env(model["path"])


def test_step(step_id: str, exe: str, model: dict, timeout: int):
    return Step(step_id, [str(BIN / exe)], timeout=timeout, gpu=True), \
        build_env(model["path"], test_model=True)


# --------------------------------------------------------------------------- model run

def run_model(model: dict, run_dir: Path, run_id: str, build: dict,
              args, state: dict) -> bool:
    """Run all steps for one model. Returns True if a STOP condition was hit."""
    mid = model["id"]
    prof = {}
    prof_step = spec_step(model)
    r = run_step(prof_step, run_dir, mid, build_env(model["path"]))
    if r["status"] == "ok":
        try:
            prof = json.loads(r["stdout"])
        except Exception:
            prof = {}
    # persist profile for later analysis
    (run_dir / "profiles").mkdir(parents=True, exist_ok=True)
    (run_dir / "profiles" / f"{mid}.profile.json").write_text(
        json.dumps(prof, ensure_ascii=False), encoding="utf-8")

    base = blank_row(run_id, model, "profile")
    base.update({"status": r["status"], "exit_code": r["exit_code"], "wall_s": r["wall_s"],
                 "raw_stdout": r["raw_stdout"], "raw_stderr": r["raw_stderr"]})
    base.update({"build_id": build["build_id"], "tir_dll_sha256": build["dll_sha"],
                 "git_head": build["git_head"], "git_dirty_count": build["dirty"]})
    spec = extract_spec(prof)
    base.update(spec)
    append_row(run_dir, base)

    ctx_train = spec.get("ctx_train") or 0
    nextn = spec.get("nextn_layers") or 0
    weights_gb = (spec.get("weights_bytes") or 0) / 1e9

    # choose ctx ladder; probe decides what actually fits. a model whose weights
    # alone exceed the card gets one attempt, not three: the failure is the result
    oversize = weights_gb > 7.5
    ladder = ([2048] if oversize
              else ([c for c in (16384, 8192, 4096) if ctx_train == 0 or c <= ctx_train] or [2048]))
    ctx_ref = None
    probe = None
    for c in ladder:
        if args.skip_gpu:
            ctx_ref = c
            break
        step, env = bench_step("probe", model, c, 0, 8)
        r = run_step(step, run_dir, mid, env)
        row = blank_row(run_id, model, f"probe_{c}")
        row.update(spec)
        fill_bench_row(row, r, parse_bench(r["stdout"], r["stderr"]), c, 0, 8, "capital_france")
        append_row(run_dir, row)
        if r["status"] == "ok":
            ctx_ref = c
            probe = (r, parse_bench(r["stdout"], r["stderr"]))
            break
        if r["crash_signature"] in ("illegal_memory_access", "access_violation",
                                    "device_unavailable"):
            return True  # STOP
    if ctx_ref is None:
        # every ladder entry failed: record and move on
        return False

    # a probe that leaves <800 MiB headroom thrashes on longer prompts (Windows
    # oversubscribes VRAM to system RAM); long-context numbers would measure swap
    probe_peak = (probe[0].get("vram_peak_mib") or 0) if probe else 0
    edge = probe_peak > 7300

    ctx_low = 4096 if 4096 <= ctx_ref else ctx_ref
    ctx_high = 32768 if ctx_ref >= 32768 and (ctx_train == 0 or 32768 <= ctx_train) else None

    def do_bench(step_id, ctx, mtp, n_predict, spec_debug=False):
        step, env = bench_step(step_id, model, ctx, mtp, n_predict, spec_debug=spec_debug)
        r = run_step(step, run_dir, mid, env)
        row = blank_row(run_id, model, step_id)
        row.update(spec)
        fill_bench_row(row, r, parse_bench(r["stdout"], r["stderr"]),
                       ctx, mtp, n_predict, "capital_france")
        append_row(run_dir, row)
        return r

    do_bench("rate_plain", ctx_ref, 0, 128)
    mtp_ok = False
    if nextn > 0:
        r5 = do_bench("rate_mtp", ctx_ref, 1, 128, spec_debug=True)
        mtp_ok = r5["status"] == "ok"
        if mtp_ok:
            do_bench("mtp_attrib", ctx_ref, 1, 512, spec_debug=True)

    # TTFT sweep
    for tag, target in (("S", 128), ("M", 2048)):
        step, env = ceiling_step(f"ttft_{tag}", model, ctx_ref, target)
        r = run_step(step, run_dir, mid, env)
        row = blank_row(run_id, model, f"ttft_{tag}")
        row.update(spec)
        fill_ceiling_row(row, r, parse_ceiling(r["stdout"], r["stderr"]), ctx_ref, target)
        append_row(run_dir, row)
    if ctx_ref >= 12288 and not edge:
        step, env = ceiling_step("ttft_L", model, ctx_ref, 8192)
        r = run_step(step, run_dir, mid, env)
        row = blank_row(run_id, model, "ttft_L")
        row.update(spec)
        fill_ceiling_row(row, r, parse_ceiling(r["stdout"], r["stderr"]), ctx_ref, 8192)
        append_row(run_dir, row)

    # extra ctx points
    if ctx_low != ctx_ref:
        do_bench("ctx_low", ctx_low, 0, 128)
    if ctx_high and not edge:
        do_bench("ctx_high", ctx_high, 0, 128)

    # power
    step, env = power_step(model, ctx_ref, run_dir)
    r = run_step(step, run_dir, mid, env)
    row = blank_row(run_id, model, "power")
    row.update(spec)
    row.update({"status": r["status"], "exit_code": r["exit_code"], "wall_s": r["wall_s"],
                "raw_stdout": r["raw_stdout"], "raw_stderr": r["raw_stderr"],
                "ctx": ctx_ref, "vram_peak_mib": r["vram_peak_mib"]})
    pj = run_dir / "raw" / mid / "power.jsonl"
    p = parse_power(Path(str(pj)))
    for k in ("avg_power_w", "avg_sm_mhz", "avg_mem_mhz", "min_mem_mhz", "max_temp_c",
              "j_per_token_decode", "tokens_per_j_decode", "samples"):
        if k in p:
            row["power_samples" if k == "samples" else k] = p[k]
    append_row(run_dir, row)

    # determinism / parity tests
    for step_id, exe, timeout in (("test_profile", T_PROFILE, 600),
                                  ("test_prefill", T_PREFILL, 900)):
        step, env = test_step(step_id, exe, model, timeout)
        if step_id == "test_prefill" and (edge or ctx_ref < 16384 or (ctx_train and ctx_train < 16384)):
            row = blank_row(run_id, model, step_id)
            row.update(spec)
            row.update({"status": "skip", "skip_reason": "vram_edge" if edge else "prefill_needs_ctx16384"})
            append_row(run_dir, row)
            continue
        r = run_step(step, run_dir, mid, env)
        row = blank_row(run_id, model, step_id)
        row.update(spec)
        row.update({"status": r["status"], "exit_code": r["exit_code"],
                    "wall_s": r["wall_s"], "raw_stdout": r["raw_stdout"],
                    "raw_stderr": r["raw_stderr"], "crash_signature": r["crash_signature"]})
        if step_id == "test_profile":
            pp = parse_profile(r["stdout"])
            row["perf_valid"] = pp.get("ok")
        else:
            pf = parse_prefill(r["stdout"])
            row["prefill_overall"] = pf.get("overall")
            cases = {c["prompt_tokens"]: c for c in pf.get("cases", [])}
            for key, label in ((5, "5"), (130, "130"), (520, "520")):
                hit = None
                for n, c in cases.items():
                    if abs(n - key) <= 6:
                        hit = c
                        break
                row[f"prefill_parity_{label}"] = hit["parity"] if hit else None
            if "default" in pf:
                row["prefill_default_expect"] = pf["default"]["expect"]
                row["prefill_default_match"] = pf["default"]["match"]
                row["prefill_default_parity"] = pf["default"]["parity"]
            row["prefill_default_verdict_expected"] = expected_default_verdict(
                spec.get("arch"), nextn > 0)
        append_row(run_dir, row)

    if mtp_ok:
        step, env = test_step("test_mtp", T_MTP, model, 1200)
        r = run_step(step, run_dir, mid, env)
        row = blank_row(run_id, model, "test_mtp")
        row.update(spec)
        row.update({"status": r["status"], "exit_code": r["exit_code"],
                    "wall_s": r["wall_s"], "raw_stdout": r["raw_stdout"],
                    "raw_stderr": r["raw_stderr"], "crash_signature": r["crash_signature"]})
        mp = parse_mtp(r["stdout"])
        row["mtp_parity_tokens"] = mp.get("parity_tokens")
        row["mtp_first_divergence"] = mp.get("first_divergence")
        row["mtp_cache_cold_ms"] = mp.get("cache_cold_ms")
        row["mtp_cache_warm_ms"] = mp.get("cache_warm_ms")
        row["mtp_cancel_tokens"] = mp.get("cancel_tokens")
        row["mtp_reuse_tokens"] = mp.get("reuse_tokens")
        row["mtp_oversize_reject_tokens"] = mp.get("oversize_reject_tokens")
        append_row(run_dir, row)
    return False


def expected_default_verdict(arch, has_nextn: bool) -> str:
    whitelist = {"llama", "qwen3", "qwen35", "nemotron_h"}
    engine = 1 if arch not in whitelist else (2 if has_nextn else 512)
    test = 2 if has_nextn else 512
    return "PASS" if engine == test else "FAIL(policy_mismatch)"


def extract_spec(prof: dict) -> dict:
    if not prof:
        return {}
    keys = {
        "arch": "arch", "n_layer": "n_layer", "n_trunk_layers": "n_trunk_layers",
        "nextn_layers": "nextn_layers", "n_embd": "n_embd", "n_expert": "n_expert",
        "ctx_train": "ctx_train", "hybrid_ssm": "hybrid_ssm",
        "sliding_window": "sliding_window", "weights_bytes": "total_bytes",
        "kv_est_mib": "kv_mib",
    }
    out = {}
    for dst, src in keys.items():
        if src in prof:
            out[dst] = prof[src]
    kv = prof.get("kv") or {}
    if isinstance(kv, dict):
        if "mib" in kv:
            out["kv_est_mib"] = kv["mib"]
    return out


def fill_bench_row(row, r, pb, ctx, mtp, n_predict, prompt_id):
    row.update({"status": r["status"], "skip_reason": r["skip_reason"],
                "exit_code": r["exit_code"], "wall_s": r["wall_s"],
                "raw_stdout": r["raw_stdout"], "raw_stderr": r["raw_stderr"],
                "poll_csv": r["poll_csv"], "crash_signature": r["crash_signature"],
                "error_code": r["error_code"], "ctx": ctx, "ctx_requested": ctx,
                "kv_q4": 1, "mtp": mtp, "n_predict": n_predict,
                "prompt_id": prompt_id, "runs": 3,
                "vram_before_mib": r["vram_before_mib"],
                "vram_peak_mib": r["vram_peak_mib"], "vram_after_mib": r["vram_after_mib"],
                "min_mem_mhz": r["min_mem_mhz"], "max_temp_c": r["max_temp_c"]})
    head = pb.get("headline") or {}
    row["tok_s_avg"] = head.get("tok_s_avg")
    row["tok_s_best"] = head.get("tok_s_best")
    row["ttft_ms"] = head.get("ttft_ms")
    row["acceptance"] = head.get("acceptance")
    row["mean_len"] = head.get("mean_len")
    row["gen_tokens"] = head.get("gen_tokens")
    row["mtp_effective"] = mtp if (head.get("acceptance") or 0) > 0 else 0
    last = pb["runs"][-1] if pb.get("runs") else {}
    for k in ("eval_ms", "prompt_eval_ms", "sampler_ms", "step_us", "detok_us",
              "callback_us", "graph_reused", "graph_reallocs_same", "graph_reallocs_diff",
              "decode_ms", "prompt_tokens"):
        if k in last:
            row[k] = last[k]
    row["runs_consistent"] = pb.get("runs_consistent")
    row["spec_steps"] = pb.get("spec_steps")
    row["spec_drafted"] = pb.get("spec_drafted")
    row["spec_accepted"] = pb.get("spec_accepted")
    row["draft_eval_ms"] = pb.get("draft_eval_ms")
    row["draft_p_eval_ms"] = pb.get("draft_p_eval_ms")
    row["draft_n_eval"] = pb.get("draft_n_eval")
    for k, v in pb.get("buffers", {}).items():
        row[k] = v
    row.update(roofline_ledger(row))
    wg = (row.get("weights_bytes") or 0) / 1e9
    row.update(roof_max(wg, (row.get("kv_est_mib") or 0) / 1024.0))
    rf = row.get("roof_max_full_tok_s")
    if rf and row.get("tok_s_avg"):
        row["roofline_eff"] = round(row["tok_s_avg"] / rf, 3)
    if r["gpu_before"]:
        g = r["gpu_before"]
        row["gpu_before_sm_mhz"] = g.get("clocks.sm")
        row["gpu_before_mem_mhz"] = g.get("clocks.mem")
        row["gpu_before_temp_c"] = g.get("temperature.gpu")
        row["gpu_before_power_w"] = g.get("power.draw")
    if r["gpu_after"]:
        g = r["gpu_after"]
        row["gpu_after_sm_mhz"] = g.get("clocks.sm")
        row["gpu_after_mem_mhz"] = g.get("clocks.mem")
        row["gpu_after_temp_c"] = g.get("temperature.gpu")
        row["gpu_after_power_w"] = g.get("power.draw")


def fill_ceiling_row(row, r, cj, ctx, target):
    row.update({"status": r["status"], "exit_code": r["exit_code"], "wall_s": r["wall_s"],
                "raw_stdout": r["raw_stdout"], "raw_stderr": r["raw_stderr"],
                "poll_csv": r["poll_csv"], "crash_signature": r["crash_signature"],
                "ctx": ctx, "kv_q4": cj.get("kv_q4", 1), "mtp": 0, "n_predict": 128,
                "prompt_id": "ceiling_unit", "prompt_tokens_target": target,
                "prompt_tokens_actual": cj.get("prompt_tokens"), "runs": cj.get("runs"),
                "prefill_batch": 512, "prefill_batch_source": "env_override",
                "vram_peak_mib": r["vram_peak_mib"]})
    for k in ("tok_s_p50", "tok_s_p95", "tok_s_min", "tok_s_max", "ttft_ms", "decode_ms",
              "eval_ms", "prompt_eval_ms", "sampler_ms", "step_us", "detok_us",
              "callback_us", "graph_reused", "graph_reallocs_same",
              "graph_reallocs_diff", "gen_tokens"):
        if k in cj:
            row[k] = cj[k]
    for k, v in (cj.get("buffers") or {}).items():
        row[k] = v
    row.update(roofline_ledger(row))
    wg = (row.get("weights_bytes") or 0) / 1e9
    row.update(roof_max(wg, (row.get("kv_est_mib") or 0) / 1024.0))
    rf = row.get("roof_max_full_tok_s")
    if rf and row.get("tok_s_p50"):
        row["roofline_eff"] = round(row["tok_s_p50"] / rf, 3)


# --------------------------------------------------------------------------- main

def load_registry() -> list:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    models = data["models"]
    for m in models:
        p = Path(m["path"])
        m["exists"] = p.exists()
        m["bytes"] = p.stat().st_size if p.exists() else None
    return models


def build_info() -> dict:
    dll = BIN / "tir.dll"
    exes = {}
    for exe in (BENCH, CEILING, T_PROFILE, T_PREFILL, T_MTP):
        p = BIN / exe
        exes[exe] = sha256_16(p) if p.exists() else None
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=20).stdout.strip()
        dirty = len(subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                                   capture_output=True, text=True, timeout=20).stdout.splitlines())
    except Exception:
        head, dirty = "", -1
    return {"build_id": datetime.now(TZ).strftime("%Y%m%d-%H%M"),
            "dll_sha": sha256_16(dll) if dll.exists() else None,
            "exe_sha": exes, "git_head": head, "dirty": dirty}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--resume", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--max-wall-hours", type=float, default=4.0)
    ap.add_argument("--skip-gpu", action="store_true")
    ap.add_argument("--cooldown", type=float, default=30.0)
    args = ap.parse_args(argv)

    models = load_registry()
    missing = [m["id"] for m in models if not m.get("exists")]
    if missing:
        print("MISSING:", ", ".join(missing), file=sys.stderr)
        return 4

    todo_ids = [s for s in args.models.split(",") if s]
    todo = [m for m in models if not m.get("exclude") and (not todo_ids or m["id"] in todo_ids)]
    todo.sort(key=lambda m: m["bytes"] or 0)  # small first

    run_id = args.run_id or args.resume or run_id_new()
    run_dir = OUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    build = build_info()
    run_json = {"schema": "tir.matrix-run/v1", "run_id": run_id, "started_at": now_iso(),
                "build": build, "models": [m["id"] for m in todo],
                "excluded": [m["id"] for m in models if m.get("exclude")],
                "args": vars(args)}
    atomic_json(run_dir / "run.json", run_json)

    if args.dry_run:
        print(f"run_id={run_id} models={len(todo)} dll={build['dll_sha']}")
        for m in todo:
            print(f"  {m['id']:<24} {m['bytes']/2**30:5.2f} GiB  {m['source']}  {m.get('notes','')}")
        print("dry-run: profile step executed only for models listed with --models; no GPU used")
        return 0

    if not args.skip_gpu:
        gate = gpu_gate()
        if not gate["ok"]:
            print("STOP gpu_gate:", gate["reason"], file=sys.stderr)
            return 3

    started = time.time()
    state_path = run_dir / "state.json"
    state = {"done": {}, "stop": None}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))

    for idx, m in enumerate(todo):
        if time.time() - started > args.max_wall_hours * 3600:
            state["stop"] = "max_wall_hours"
            atomic_json(state_path, state)
            print("STOP max_wall_hours", file=sys.stderr)
            return 3
        if state.get("done", {}).get(m["id"]) == "ok":
            print(f"skip {m['id']} (done)")
            continue
        print(f"== {m['id']} ({idx + 1}/{len(todo)})")
        cd = wait_cooldown(60.0, args.cooldown) if not args.skip_gpu else {}
        stop = run_model(m, run_dir, run_id, build, args, state)
        state.setdefault("done", {})[m["id"]] = "stop" if stop else "ok"
        for k in ("cooldown_s", "cooldown_temp_c"):
            state.setdefault("cooldown", {})[m["id"]] = cd
        atomic_json(state_path, state)
        if stop:
            state["stop"] = "device_error"
            atomic_json(state_path, state)
            print("STOP device error", file=sys.stderr)
            return 3

    n = write_csv(run_dir)
    print(f"rows={n} -> {run_dir / 'master.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
