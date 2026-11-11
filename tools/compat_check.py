#!/usr/bin/env python3
"""TIR-A compatibility gate: ModelProfile -> PASS / WARN / REFUSE.

Pure function, no file or device access: all facts come from the profile JSON
that `tier_gguf.py` emits. The caller must generate the profile at the same ctx
and kv type it asks about (S1 always uses 16384 / q4_0).

Precedence: REFUSE > WARN > PASS. Reason and warning strings are stable ids,
not prose, so callers can switch on them.
"""
MIB = 1048576

# Activation / graph scratch allowance used by the residency estimate.
COMPUTE_MIB = 512

COMPAT_SCHEMA = "tir.compat/v1"

SUPPORTED_ARCH = {"llama", "qwen3", "qwen35", "gemma4", "nemotron_h", "glm4", "spark2_5"}

# S1 proves exactly this set on the local 1.1B-9B models (see L2 S1 blueprint).
# Any other type must be added only after it is benched, not by guesswork.
# Q5_0: nemotron4b Q4_K_M holds 49 of them (token_embd + ssm_in/ffn_up) and
# benched 100.27 tok/s at 128 tokens under 9ec16f8.
SUPPORTED_QUANT = {"F32", "F16", "BF16", "Q4_0", "Q4_K", "Q5_0", "Q5_K", "Q6_K", "Q8_0", "Q1_0"}


def check_compat(profile, runtime=None, requested_ctx=16384, requested_mtp=False,
                 vram_mib=8000, ram_mib=15000):
    """Judge whether this profile can be served by the S1 runtime.

    runtime overrides the compile-time capability tables and may carry:
      arch    - set of supported arch names
      quant   - set of supported ggml type names
      mmproj  - True when the runtime can load a vision projector
    """
    rt = runtime or {}
    archs = rt.get("arch", SUPPORTED_ARCH)
    quants = rt.get("quant", SUPPORTED_QUANT)
    rt_mmproj = bool(rt.get("mmproj", False))

    arch = profile.get("arch", "unknown")
    tensor_types = list(profile.get("tensor_types") or [])
    weights_mib = float(profile.get("total_mib") or 0.0)
    if not weights_mib:
        weights_mib = int(profile.get("total_bytes", 0) or 0) / MIB
    kv_mib = float((profile.get("kv") or {}).get("mib", 0.0) or 0.0)
    ctx_train = int(profile.get("ctx_train", 0) or 0)
    n_expert = int(profile.get("n_expert", 0) or 0)
    has_nextn = bool(profile.get("mtp")) or int(profile.get("nextn_layers", 0) or 0) > 0
    has_template = bool(profile.get("chat_template"))
    has_vision = bool(profile.get("mmproj") or profile.get("vision"))

    resident = weights_mib + kv_mib + COMPUTE_MIB <= vram_mib

    reasons = []
    if arch not in archs:
        reasons.append("unsupported_arch")
    if any(t not in quants for t in tensor_types):
        reasons.append("unsupported_quant")
    if not resident:
        reasons.append("weights_exceed_vram")
        # weights still fit host RAM, so a later tiered/streaming slice can take it
        if weights_mib <= vram_mib + ram_mib:
            reasons.append("tiered_required")
    if int(requested_ctx) > ctx_train:
        reasons.append("ctx_exceeds_train")

    warnings = []
    if requested_mtp and not has_nextn:
        warnings.append("mtp_fallback")
    if not has_template:
        warnings.append("no_chat_template")
    if has_vision and not rt_mmproj:
        warnings.append("vision_unsupported")

    capabilities = []
    if resident:
        capabilities.append("resident")
    if has_nextn:
        capabilities.append("mtp")
    if has_template:
        capabilities.append("chat_template")
    if n_expert > 0:
        capabilities.append("moe")
    if has_vision and rt_mmproj:
        capabilities.append("vision")

    if reasons:
        status = "REFUSE"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "schema": COMPAT_SCHEMA,
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "arch": arch,
        "quant": profile.get("file_type") or "+".join(tensor_types) or "unknown",
        "weights_mib": round(weights_mib, 2),
        "kv_mib": round(kv_mib, 2),
        "capabilities": capabilities,
    }
