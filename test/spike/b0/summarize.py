import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        return None
    for line in reversed(open(path, "r", encoding="utf-8", errors="replace").read().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return None


def ids(x):
    return x.get("token_ids") if x else None


def main():
    a = load("b0a.json")
    b = load("b0b.json")
    c = load("b0c.json")
    d = load("b0d.json")
    e = []
    ep = os.path.join(BASE, "b0e.json")
    if os.path.exists(ep):
        for line in open(ep, "r", encoding="utf-8", errors="replace").read().splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    e.append(json.loads(line))
                except Exception:
                    pass

    out = {
        "files": {k: (v is not None) for k, v in (("a", a), ("b", b), ("c", c), ("d", d))},
        "baseline_ms": a["ms_per_token"] if a else None,
        "baseline_tok_s": a["tok_s"] if a else None,
        "callback": {
            "cb_false": b["cb_false"] if b else None,
            "cb_true": b["cb_true"] if b else None,
            "equal": (b["cb_false"] == b["cb_true"]) if b else None,
            "ms": b["ms_per_token"] if b else None,
            "tok_s": b["tok_s"] if b else None,
        },
        "zero_copy": {
            "ms": c["ms_per_token"] if c else None,
            "delta_vs_b": (c["ms_per_token"] - b["ms_per_token"]) if (b and c) else None,
            "ids_equal_tier": (ids(c) == ids(b)) if (b and c) else None,
            "ids_equal_stock": (ids(c) == ids(a)) if (a and c) else None,
            "copy_ms_per_token": c.get("copy_ms_per_token") if c else None,
            "pointer_type": c.get("pointer_type") if c else None,
        },
        "h2d": {
            "ms": d["ms_per_token"] if d else None,
            "delta_vs_b": (d["ms_per_token"] - b["ms_per_token"]) if (b and d) else None,
            "ids_equal_tier": (ids(d) == ids(b)) if (b and d) else None,
            "ids_equal_stock": (ids(d) == ids(a)) if (a and d) else None,
            "copy_ms_per_token": d.get("copy_ms_per_token") if d else None,
            "tensor": d.get("tensor") if d else None,
            "tensor_mib": d.get("tensor_mib") if d else None,
        },
        "tier_vs_stock_ids_equal": (ids(b) == ids(a)) if (a and b) else None,
        "h2d_bench": e,
    }

    # gate: 32MB < 5ms, 256MB-equivalent scaled, token ids equal, cb equal
    gate = True
    notes = []
    if not (b and b.get("cb_false") == b.get("cb_true")):
        gate = False
        notes.append("callback counts differ")
    if not (c and ids(c) == ids(b)):
        gate = False
        notes.append("zero-copy token ids differ from tier baseline")
    if not (d and ids(d) == ids(b)):
        gate = False
        notes.append("h2d token ids differ from tier baseline")
    if b and c and (c["ms_per_token"] - b["ms_per_token"]) > 10.0:
        gate = False
        notes.append("zero-copy delta > 10 ms")
    # approved scaled threshold: 15 ms at 256 MiB -> 15 * tensor_mib / 256
    if b and d:
        cap = d.get("tensor_mib") or 256.0
        limit = 15.0 * cap / 256.0
        if (d["ms_per_token"] - b["ms_per_token"]) > limit:
            gate = False
            notes.append("h2d delta > scaled limit %.1f ms" % limit)
        out["h2d"]["scaled_limit_ms"] = round(limit, 2)
    if e:
        best = max(x.get("gbps", 0.0) for x in e)
        out["h2d_bench_max_gbps"] = best
        if best < 15.0:
            gate = False
            notes.append("h2d bandwidth < 15 GB/s")
    else:
        notes.append("h2d bandwidth bench missing")
    if a and b and ids(a) != ids(b):
        notes.append("tier-mode baseline differs from stock baseline (fusion/graph disabled); gate uses tier baseline")
    out["gate_pass"] = gate
    out["notes"] = notes

    with open(os.path.join(BASE, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
