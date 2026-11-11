#!/usr/bin/env python3
"""Assemble paper.md from the chapter files and replace figure anchors.

Order: 00-front, 01-environment, 02a-stages-p0-s2, 02b-1, 02b-2,
       03-playbook, 99-appendix.
Run: python assemble.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = [
    "00-front.md",
    "01-environment.md",
    "02a-problems.md",
    "02b-evidence.md",
    "02c-matrix.md",
    "03-playbook.md",
    "99-appendix.md",
]

CAPTIONS = {
    "fig1": "图 1  本机实测有效带宽：显存、内存、PCIe 与 NVMe",
    "fig2": "图 2  开发参考的开源项目：三类关系",
    "fig3": "图 3  9B 的速率演进与口径变化",
    "fig4": "图 4  128 token 的时间分解：plain 与 MTP",
    "fig5": "图 5  权重体积与 8 GiB 显存的关系",
    "fig6": "图 6  20 模型在 128 token 下的 decode 速率",
    "fig7": "图 7  TTFT 随 prompt 长度变化",
    "fig8": "图 8  失败与回退：试过、测过、放弃或保留",
}


def han_count(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def main():
    chunks = []
    total_han = 0
    for name in PARTS:
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            print(f"skip missing {name}")
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        text = re.sub(
            r"^<!-- FIG:(fig\d) -->$",
            lambda m: f"![{CAPTIONS[m.group(1)]}](figures/{m.group(1)}.png)",
            text,
            flags=re.M,
        )
        left = len(re.findall(r"<!-- FIG:", text))
        if left:
            print(f"WARN {name}: {left} unreplaced FIG anchors")
        chunks.append(text)
        n = han_count(text)
        total_han += n
        print(f"{name}: han={n}")

    out = "\n\n".join(chunks) + "\n"
    out_path = os.path.join(HERE, "paper.md")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"wrote {out_path}: chars={len(out)} han={han_count(out)} (sum parts {total_han})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
