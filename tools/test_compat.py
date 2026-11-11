#!/usr/bin/env python3
"""S1 test suite: tir.compat/v1 profile fields and the pure compat gate.

Run: python -m unittest discover -s tools -p "test_compat.py" -v
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import tier_gguf
from compat_check import SUPPORTED_ARCH, SUPPORTED_QUANT, check_compat
from run_compat import MTP_MIN_TOK_S, evaluate_gate, kv_mismatch

QWEN9B = r"E:\model\bionic\Qwen\Qwen3.8-9B-Distill-GGUF\Qwen3.8-9B-Q5_K_M.gguf"
BONSAI = r"E:\model\bionic\lmstudio-community\Bonsai-27B-GGUF\Bonsai-27B-Q1_0.gguf"


def make_profile(**over):
    """Synthetic qwen9b profile: the PASS baseline used by the gate tests."""
    profile = {
        "schema": "tir.profile/v1",
        "arch": "qwen35",
        "n_layer": 33,
        "nextn_layers": 1,
        "mtp": True,
        "ctx_train": 262144,
        "n_expert": 0,
        "total_mib": 6324.36,
        "file_type": "Q5_K_M",
        "tensor_types": ["F32", "Q5_K", "Q6_K"],
        "chat_template": True,
        "tied_output": False,
        "compat_schema": "tir.compat/v1",
        "kv": {"ctx": 16384, "type": "q4_0", "mib": 128.0},
    }
    profile.update(over)
    return profile


class CompatGateTest(unittest.TestCase):
    def test_qwen9b_pass(self):
        r = check_compat(make_profile(), requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["schema"], "tir.compat/v1")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"], [])
        self.assertEqual(r["arch"], "qwen35")
        self.assertEqual(r["quant"], "Q5_K_M")
        self.assertAlmostEqual(r["weights_mib"], 6324.36, places=2)
        self.assertAlmostEqual(r["kv_mib"], 128.0, places=2)
        self.assertEqual(r["capabilities"], ["resident", "mtp", "chat_template"])

    def test_unknown_arch_refuse(self):
        r = check_compat(make_profile(arch="mamba9"), requested_mtp=True)
        self.assertEqual(r["status"], "REFUSE")
        self.assertIn("unsupported_arch", r["reasons"])

    def test_unsupported_quant_refuse(self):
        r = check_compat(make_profile(tensor_types=["F32", "Q2_0"]), requested_mtp=True)
        self.assertEqual(r["status"], "REFUSE")
        self.assertIn("unsupported_quant", r["reasons"])
        self.assertNotIn("Q2_0", SUPPORTED_QUANT)

    def test_spark_bf16_refuse_vram(self):
        spark = make_profile(
            arch="spark2_5",
            nextn_layers=0,
            mtp=False,
            total_mib=8229.0,
            file_type="BF16",
            tensor_types=["BF16", "F32"],
            kv={"ctx": 16384, "type": "q4_0", "mib": 96.0},
        )
        r = check_compat(spark, requested_ctx=16384, requested_mtp=False)
        self.assertEqual(r["status"], "REFUSE")
        self.assertIn("weights_exceed_vram", r["reasons"])
        self.assertIn("tiered_required", r["reasons"])

    def test_gemma26_tiered_required(self):
        gemma = make_profile(
            arch="gemma4",
            total_mib=13755.0,
            file_type="Q4_0",
            tensor_types=["F32", "Q4_0", "Q6_K"],
            n_expert=128,
            kv={"ctx": 16384, "type": "q4_0", "mib": 288.0},
        )
        r = check_compat(gemma, requested_ctx=16384, requested_mtp=False)
        self.assertEqual(r["status"], "REFUSE")
        self.assertIn("tiered_required", r["reasons"])

    def test_ctx_exceeds_train_refuse(self):
        r = check_compat(make_profile(ctx_train=8192), requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["status"], "REFUSE")
        self.assertIn("ctx_exceeds_train", r["reasons"])

    def test_mtp_fallback_warn(self):
        r = check_compat(make_profile(nextn_layers=0, mtp=False), requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["status"], "WARN")
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"], ["mtp_fallback"])

    def test_no_chat_template_warn(self):
        r = check_compat(make_profile(chat_template=False), requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["status"], "WARN")
        self.assertEqual(r["warnings"], ["no_chat_template"])

    def test_weights_beyond_vram_plus_ram_refuse_only_vram(self):
        # 30000 MiB does not fit VRAM+RAM either, so tiering cannot save it
        profile = make_profile(total_mib=30000.0)
        r = check_compat(profile, requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["status"], "REFUSE")
        self.assertEqual(r["reasons"], ["weights_exceed_vram"])
        self.assertNotIn("tiered_required", r["reasons"])

    def test_weights_between_vram_and_ram_refuse_tiered(self):
        profile = make_profile(total_mib=12000.0)
        r = check_compat(profile, requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["status"], "REFUSE")
        self.assertIn("weights_exceed_vram", r["reasons"])
        self.assertIn("tiered_required", r["reasons"])

    def test_refuse_beats_warn(self):
        # REFUSE wins the status, but both warnings still surface
        profile = make_profile(arch="mamba9", nextn_layers=0, mtp=False, chat_template=False)
        r = check_compat(profile, requested_ctx=16384, requested_mtp=True)
        self.assertEqual(r["status"], "REFUSE")
        self.assertEqual(r["reasons"], ["unsupported_arch"])
        self.assertIn("no_chat_template", r["warnings"])
        self.assertIn("mtp_fallback", r["warnings"])

    def test_vision_unsupported_warn(self):
        r = check_compat(make_profile(mmproj="mmproj-F16.gguf"), requested_ctx=16384,
                         requested_mtp=True)
        self.assertEqual(r["status"], "WARN")
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"], ["vision_unsupported"])

    def test_supported_quant_is_the_proven_s1_set(self):
        self.assertEqual(SUPPORTED_QUANT, {
            "F32", "F16", "BF16", "Q4_0", "Q4_K", "Q5_0", "Q5_K", "Q6_K", "Q8_0", "Q1_0",
        })
        for unproven in ("Q4_1", "Q5_1", "Q2_K", "Q3_K", "Q8_K", "IQ4_NL", "IQ4_XS"):
            self.assertNotIn(unproven, SUPPORTED_QUANT)

    def test_q1_0_block_size(self):
        self.assertEqual(tier_gguf.TYPE_SIZE[41], (128, 18))
        self.assertEqual(tier_gguf.tensor_nbytes(41, [128]), 18)
        self.assertEqual(tier_gguf.TYPE_NAMES[41], "Q1_0")
        self.assertEqual(tier_gguf.type_name(99), "T99")

    @unittest.skipUnless(os.path.exists(QWEN9B), f"model absent: {QWEN9B}")
    def test_real_qwen9b_profile_fields(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "tier_gguf.py"), QWEN9B, "--ctx", "16384", "--kv", "q4_0"],
            capture_output=True, text=True, encoding="utf-8", timeout=300, check=True,
        ).stdout
        p = json.loads(out)
        self.assertEqual(p["schema"], "tir.profile/v1")
        self.assertEqual(p["compat_schema"], "tir.compat/v1")
        self.assertIs(p["chat_template"], True)
        self.assertIs(p["tied_output"], False)
        self.assertIn("Q5_K", p["tensor_types"])
        self.assertEqual(len(p["layers"]), p["n_layer"])
        self.assertTrue(all(isinstance(t["type"], int) for t in p["tensors"]))
        derived = sorted({tier_gguf.type_name(t["type"]) for t in p["tensors"]})
        self.assertEqual(p["tensor_types"], derived)

    @unittest.skipUnless(os.path.exists(BONSAI), f"model absent: {BONSAI}")
    def test_bonsai_q1_0_profile_parses(self):
        out = subprocess.run(
            [sys.executable, os.path.join(HERE, "tier_gguf.py"), BONSAI, "--ctx", "16384", "--kv", "q4_0"],
            capture_output=True, text=True, encoding="utf-8", timeout=300, check=True,
        ).stdout
        p = json.loads(out)
        self.assertIn("Q1_0", p["tensor_types"])


class GateTest(unittest.TestCase):
    """The run_compat hard gate: only S1_GATE_OK passes, REFUSE is not a failure."""

    @staticmethod
    def model(name, status, tok_s_avg=None):
        return {"name": name, "status": status, "tok_s_avg": tok_s_avg}

    def test_gate_ok(self):
        gate, _ = evaluate_gate([self.model("minicpm5", "OK", 300.0),
                                 self.model("qwen9b", "OK", MTP_MIN_TOK_S)])
        self.assertEqual(gate, "S1_GATE_OK")

    def test_gate_refuse_is_not_a_failure(self):
        gate, _ = evaluate_gate([self.model("nemotron4b", "REFUSE"),
                                 self.model("qwen9b", "OK", 70.0)])
        self.assertEqual(gate, "S1_GATE_OK")

    def test_gate_failed_on_non_ok_model(self):
        for status in ("FAIL", "WARN"):
            gate, detail = evaluate_gate([self.model("nemotron4b", status, 100.0),
                                          self.model("qwen9b", "OK", 70.0)])
            self.assertEqual(gate, "S1_GATE_FAILED")
            self.assertIn("nemotron4b", detail)

    def test_gate_below_target(self):
        gate, _ = evaluate_gate([self.model("nemotron4b", "OK", 100.0),
                                 self.model("qwen9b", "OK", MTP_MIN_TOK_S - 0.1)])
        self.assertEqual(gate, "S1_GATE_BELOW_TARGET")

    def test_gate_failed_without_mtp_model(self):
        gate, _ = evaluate_gate([self.model("minicpm5", "OK", 300.0)])
        self.assertEqual(gate, "S1_GATE_FAILED")

    def test_kv_mismatch(self):
        self.assertIsNone(kv_mismatch({"kv": {"ctx": 16384, "type": "q4_0"}}))
        self.assertIsNotNone(kv_mismatch({"kv": {"ctx": 8192, "type": "q4_0"}}))
        self.assertIsNotNone(kv_mismatch({"kv": {"ctx": 16384, "type": "f16"}}))
        self.assertIsNotNone(kv_mismatch({}))


if __name__ == "__main__":
    unittest.main()
