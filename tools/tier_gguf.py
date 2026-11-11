#!/usr/bin/env python3
"""TIR-B GGUF analyzer: full metadata + tensor geometry -> ModelProfile JSON.

Usage: python tier_gguf.py <model.gguf> [--ctx 16384] [--kv q8_0]

Writes one JSON object to stdout. All sizes are bytes unless the field name ends
in _mib. KV estimates use real per-layer geometry (hybrid/SSM/sliding aware);
they are estimates and must be calibrated against llama.cpp's KV self size.
"""
import json
import struct
import sys

SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}

# ggml_type -> (elements per block, bytes per block)
TYPE_SIZE = {
    0: (1, 4),      # F32
    1: (1, 2),      # F16
    2: (32, 18),    # Q4_0
    3: (32, 20),    # Q4_1
    6: (32, 22),    # Q5_0
    7: (32, 24),    # Q5_1
    8: (32, 34),    # Q8_0
    9: (32, 36),    # Q8_1
    10: (256, 84),  # Q2_K
    11: (256, 110), # Q3_K
    12: (256, 144), # Q4_K
    13: (256, 176), # Q5_K
    14: (256, 210), # Q6_K
    15: (256, 292), # Q8_K
    16: (256, 66),  # IQ2_XXS
    17: (256, 74),  # IQ2_XS
    18: (256, 98),  # IQ3_XXS
    19: (256, 50),  # IQ1_S
    20: (256, 110), # IQ4_NL
    21: (256, 82),  # IQ3_S
    22: (256, 98),  # IQ2_S
    23: (256, 136), # IQ4_XS
    24: (1, 1),     # I8
    25: (1, 2),     # I16
    26: (1, 4),     # I32
    27: (1, 8),     # I64
    28: (1, 8),     # F64
    29: (256, 56),  # IQ1_M
    30: (1, 2),     # BF16
    34: (256, 54),  # TQ1_0
    35: (256, 66),  # TQ2_0
    41: (128, 18),  # Q1_0: QK1_0 = 128 elems, ggml_half d + 16 packed bytes
}

# ggml_type -> name, mirrors GGML_TYPE_* in ggml.h
TYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1",
    8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K", 12: "Q4_K", 13: "Q5_K",
    14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS", 17: "IQ2_XS", 18: "IQ3_XXS",
    19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS",
    24: "I8", 25: "I16", 26: "I32", 27: "I64", 28: "F64", 29: "IQ1_M",
    30: "BF16", 34: "TQ1_0", 35: "TQ2_0", 39: "MXFP4", 40: "NVFP4",
    41: "Q1_0", 42: "Q2_0",
}

# general.file_type -> LLAMA_FTYPE_* suffix
FTYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S",
    15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS",
    20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S",
    25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M",
    30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 36: "TQ1_0", 37: "TQ2_0",
    38: "MXFP4_MOE", 39: "NVFP4", 40: "Q1_0", 41: "Q2_0",
}

KV_BYTES = {"q8_0": 1.0, "q4_0": 0.5, "f16": 2.0}


def rx(f, n):
    b = f.read(n)
    if len(b) != n:
        raise EOFError("unexpected EOF")
    return b


def u32(f):
    return struct.unpack("<I", rx(f, 4))[0]


def u64(f):
    return struct.unpack("<Q", rx(f, 8))[0]


def rstr(f, wide):
    n = u64(f) if wide else u32(f)
    return rx(f, n).decode("utf-8", "replace")


def rval(f, t, wide):
    if t in SCALAR:
        fmt = SCALAR[t]
        return struct.unpack(fmt, rx(f, struct.calcsize(fmt)))[0]
    if t == 8:
        return rstr(f, wide)
    if t == 9:
        et = u32(f)
        n = u64(f) if wide else u32(f)
        return [rval(f, et, wide) for _ in range(n)]
    raise ValueError(f"unsupported metadata type {t}")


def tensor_nbytes(ttype, dims):
    numel = 1
    for d in dims:
        numel *= d
    if ttype not in TYPE_SIZE:
        raise ValueError(f"unsupported tensor type {ttype}")
    block_elems, block_bytes = TYPE_SIZE[ttype]
    return (numel // block_elems) * block_bytes


def type_name(ttype):
    return TYPE_NAMES.get(ttype, f"T{ttype}")


def parse_gguf(path):
    with open(path, "rb") as f:
        if rx(f, 4) != b"GGUF":
            raise ValueError("not a GGUF file")
        version = u32(f)
        wide = version >= 3
        n_tensors = u64(f) if wide else u32(f)
        n_kv = u64(f) if wide else u32(f)
        metadata = {}
        for _ in range(n_kv):
            key = rstr(f, wide)
            metadata[key] = rval(f, u32(f), wide)
        tensors = []
        for _ in range(n_tensors):
            name = rstr(f, wide)
            n_dims = u32(f)
            dims = [u64(f) for _ in range(n_dims)] if wide else [u32(f) for _ in range(n_dims)]
            ttype = u32(f)
            _offset = u64(f) if wide else u32(f)
            tensors.append({"name": name, "type": ttype, "dims": dims, "nbytes": tensor_nbytes(ttype, dims)})
    return metadata, tensors


def layer_of(name):
    if name.startswith("blk."):
        rest = name[4:]
        dot = rest.find(".")
        if dot > 0 and rest[:dot].isdigit():
            return int(rest[:dot]), rest[dot + 1:]
    return -1, name


def kind_of(suffix, name):
    if "exps" in suffix:
        return "expert"
    if suffix.startswith("attn") or suffix.startswith("ssm") or "attn" in suffix:
        return "attn"
    if suffix.startswith("ffn") or "ffn" in suffix:
        return "ffn"
    if "norm" in suffix:
        return "norm"
    if name.startswith("token_embd"):
        return "embed"
    if name.startswith("output"):
        return "output"
    return "other"


def kv_estimate(meta, arch, n_layer, ctx, kv_type):
    """Return (kv_bytes, per_layer list, notes)."""
    bpe = KV_BYTES[kv_type]
    head_kv = meta.get(f"{arch}.attention.head_count_kv")
    key_len = meta.get(f"{arch}.attention.key_length")
    val_len = meta.get(f"{arch}.attention.value_length")
    layers = []
    notes = []

    if arch == "qwen35":
        interval = int(meta.get(f"{arch}.full_attention_interval", 0) or 0)
        nextn = int(meta.get(f"{arch}.nextn_predict_layers", 0) or 0)
        trunk = n_layer - nextn
        if interval <= 0:
            interval = 1
        if isinstance(head_kv, list):
            kv_heads = head_kv
        else:
            kv_heads = [head_kv] * n_layer
        for i in range(trunk):
            full = (i + 1) % interval == 0
            if full:
                klen = key_len or 256
                vlen = val_len or klen
                per_token = 2 * kv_heads[i] * (klen + vlen) // 2  # K+V elements
                layers.append({"index": i, "attention": True, "n_kv": kv_heads[i], "key_len": klen,
                               "value_len": vlen, "seq_len": ctx, "bytes": int(per_token * bpe * ctx)})
            else:
                layers.append({"index": i, "attention": False, "n_kv": 0, "key_len": 0,
                               "value_len": 0, "seq_len": 0, "bytes": 0})
        notes.append("qwen35 hybrid: SSM state excluded from KV estimate")
    elif arch == "gemma4":
        swa = int(meta.get(f"{arch}.attention.sliding_window", 0) or 0)
        pattern = meta.get(f"{arch}.attention.sliding_window_pattern")
        key_swa = meta.get(f"{arch}.attention.key_length_swa")
        val_swa = meta.get(f"{arch}.attention.value_length_swa")
        for i in range(n_layer):
            local = bool(pattern[i]) if isinstance(pattern, list) else i % 6 != 5
            per_layer_kv = head_kv[i] if isinstance(head_kv, list) else head_kv
            if local:
                klen, vlen = (key_swa or 256), (val_swa or key_swa or 256)
                seq = min(ctx, swa) if swa > 0 else ctx
            else:
                klen, vlen = (key_len or 512), (val_len or key_len or 512)
                seq = ctx
            per_token = 2 * per_layer_kv * (klen + vlen) // 2
            layers.append({"index": i, "attention": True, "sliding": local, "n_kv": per_layer_kv,
                           "key_len": klen, "value_len": vlen, "seq_len": seq,
                           "bytes": int(per_token * bpe * seq)})
        notes.append("gemma4 sliding-window: local layers capped at sliding_window")
    else:
        for i in range(n_layer):
            per_layer_kv = head_kv[i] if isinstance(head_kv, list) else head_kv
            klen = key_len or 128
            vlen = val_len or klen
            per_token = 2 * per_layer_kv * (klen + vlen) // 2
            layers.append({"index": i, "attention": True, "n_kv": per_layer_kv, "key_len": klen,
                           "value_len": vlen, "seq_len": ctx,
                           "bytes": int(per_token * bpe * ctx)})
    total = sum(layer["bytes"] for layer in layers)
    return total, layers, notes


def main():
    path = sys.argv[1]
    ctx = 16384
    kv_type = "q8_0"
    for i, arg in enumerate(sys.argv):
        if arg == "--ctx" and i + 1 < len(sys.argv):
            ctx = int(sys.argv[i + 1])
        if arg == "--kv" and i + 1 < len(sys.argv):
            kv_type = sys.argv[i + 1]

    meta, tensors = parse_gguf(path)
    arch = meta.get("general.architecture", "unknown")
    n_layer = int(meta.get(f"{arch}.block_count", 0))
    n_embd = int(meta.get(f"{arch}.embedding_length", 0))
    n_head = int(meta.get(f"{arch}.attention.head_count", 0))
    head_kv = meta.get(f"{arch}.attention.head_count_kv")
    ctx_train = int(meta.get(f"{arch}.context_length", 0))
    n_expert = int(meta.get(f"{arch}.expert_count", 0) or 0)
    n_expert_used = int(meta.get(f"{arch}.expert_used_count", 0) or 0)
    nextn = int(meta.get(f"{arch}.nextn_predict_layers", 0) or 0)
    interval = int(meta.get(f"{arch}.full_attention_interval", 0) or 0)

    layer_bytes = {}
    tensors_out = []
    total_bytes = 0
    largest = {"name": "", "nbytes": 0}
    tensor_types = set()
    has_output = False
    for t in tensors:
        lidx, suffix = layer_of(t["name"])
        kind = kind_of(suffix, t["name"])
        tensors_out.append({"name": t["name"], "type": t["type"], "bytes": t["nbytes"],
                            "layer": lidx, "kind": kind})
        tensor_types.add(type_name(t["type"]))
        if t["name"] == "output.weight":
            has_output = True
        total_bytes += t["nbytes"]
        if t["nbytes"] > largest["nbytes"]:
            largest = {"name": t["name"], "nbytes": t["nbytes"]}
        if lidx >= 0:
            entry = layer_bytes.setdefault(lidx, {"attn_bytes": 0, "ffn_bytes": 0, "norm_bytes": 0, "expert_bytes": 0})
            if kind == "expert":
                entry["expert_bytes"] += t["nbytes"]
            elif kind == "attn":
                entry["attn_bytes"] += t["nbytes"]
            elif kind == "ffn":
                entry["ffn_bytes"] += t["nbytes"]
            elif kind == "norm":
                entry["norm_bytes"] += t["nbytes"]

    kv_total, kv_layers, notes = kv_estimate(meta, arch, n_layer, ctx, kv_type)
    profile_layers = []
    for i in range(n_layer):
        entry = layer_bytes.get(i, {"attn_bytes": 0, "ffn_bytes": 0, "norm_bytes": 0, "expert_bytes": 0})
        kv = kv_layers[i] if i < len(kv_layers) else {"bytes": 0}
        profile_layers.append({
            "index": i,
            "attn_bytes": entry["attn_bytes"],
            "ffn_bytes": entry["ffn_bytes"],
            "expert_bytes": entry["expert_bytes"],
            "norm_bytes": entry["norm_bytes"],
            "attention": bool(kv.get("attention", False)),
            "sliding": bool(kv.get("sliding", False)),
            "n_kv": kv.get("n_kv", 0),
            "key_len": kv.get("key_len", 0),
            "value_len": kv.get("value_len", 0),
            "kv_bytes": kv.get("bytes", 0),
        })

    ssm_state = 0
    if arch == "qwen35":
        inner = int(meta.get(f"{arch}.ssm.inner_size", 0) or 0)
        state = int(meta.get(f"{arch}.ssm.state_size", 0) or 0)
        conv = int(meta.get(f"{arch}.ssm.conv_kernel", 0) or 0)
        ssm_layers = sum(1 for i in range(n_layer - nextn) if not profile_layers[i]["attention"])
        ssm_state = ssm_layers * (inner * state * 4 + conv * inner * 4)
        notes.append("qwen35 SSM state estimated at f32; calibrate with runtime")

    hybrid_ssm = arch == "qwen35"
    sliding = arch == "gemma4" and any(layer.get("sliding") for layer in profile_layers)

    profile = {
        "schema": "tir.profile/v1",
        "model": path,
        "arch": arch,
        "n_layer": n_layer,
        "n_trunk_layers": n_layer - nextn,
        "nextn_layers": nextn,
        "n_embd": n_embd,
        "n_head": n_head,
        "n_head_kv": head_kv,
        "ctx_train": ctx_train,
        "n_expert": n_expert,
        "n_expert_used": n_expert_used,
        "mtp": nextn > 0,
        "hybrid_ssm": hybrid_ssm,
        "sliding": sliding,
        "sliding_window": int(meta.get(f"{arch}.attention.sliding_window", 0) or 0),
        "full_attention_interval": interval,
        "total_bytes": total_bytes,
        "total_mib": round(total_bytes / 1048576, 2),
        "largest_tensor": largest["name"],
        "largest_tensor_mib": round(largest["nbytes"] / 1048576, 2),
        "kv": {
            "ctx": ctx,
            "type": kv_type,
            "bytes": kv_total,
            "mib": round(kv_total / 1048576, 2),
            "ssm_state_bytes": ssm_state,
            "ssm_state_mib": round(ssm_state / 1048576, 2),
            "notes": notes,
            "layers": kv_layers,
        },
        "tensor_types": sorted(tensor_types),
        "chat_template": bool(meta.get("tokenizer.chat_template")),
        "tied_output": not has_output,
        "file_type": FTYPE_NAMES.get(int(meta["general.file_type"]), "unknown")
        if isinstance(meta.get("general.file_type"), int) else "unknown",
        "compat_schema": "tir.compat/v1",
        "layers": profile_layers,
        "tensors": tensors_out,
    }
    json.dump(profile, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

