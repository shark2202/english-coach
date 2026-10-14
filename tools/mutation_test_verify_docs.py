#!/usr/bin/env python3
"""校验器变异测试（R5 的准入条件）。

为什么需要它：二轮 L2 用变异测试证明，`tools/selftest_verify_docs.py`
当时有 3 个用例是**空断言**——把被测代码整段删掉，用例照样打 ✓。
换句话说，那套自审在为一扇它从未推开过的门背书。

**自审套件证明检查会在坏输入上触发；变异测试证明自审本身不是空转。**
两者缺一不可。本文件把「删掉新代码，用例是否会红」变成可重复执行的准入门槛。

用法：
    python3 tools/mutation_test_verify_docs.py
退出码：0 = 每处变异都被自审套件捕获；1 = 有变异逃逸（自审存在空断言）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tools" / "verify_docs.py"
SELFTEST = ROOT / "tools" / "selftest_verify_docs.py"

# (变异名, 原片段, 替换片段)——每一条都必须指向一段「承担判定」的代码，
# 而不是日志或注释。替换后若自审仍全绿，说明覆盖它的用例是空断言。
MUTATIONS: list[tuple[str, str, str]] = [
    (
        "引号归一化失效（首轮真实 bug 的回归）",
        "return s[1:-1]",
        "return s  # MUTANT",
    ),
    (
        "REF001 的「待定义」豁免分支被删",
        'if re.search(r"待定义|预留|TBD|待补", line):',
        "if False:  # MUTANT",
    ),
    (
        "OWN002 不再拦截未授权文件",
        'fail(path.name, "OWN002", "契约中无任何批次 owns 此文件——未授权创建")',
        "pass  # MUTANT",
    ),
    (
        "OWN001 不再拦截归属不符",
        'elif declared != actual:',
        "elif False:  # MUTANT",
    ),
    (
        "MAN001 内容指纹比对恒为真",
        "if cur == frozen or cur in legal.get(rel, set()):",
        "if True:  # MUTANT",
    ),
    (
        "FIX001 不再核对修正证据",
        'if kind == "contains" and not present:',
        "if False:  # MUTANT",
    ),
    (
        "RM001 不再核对 README 索引",
        "for f in sorted(REQ_DIR.glob(\"*.md\")):",
        "for f in []:  # MUTANT",
    ),
    (
        "CNT001 不再核对关系数",
        "if rel_decl and int(rel_decl.group(1)) != rel_actual:",
        "if False:  # MUTANT",
    ),
    (
        "EMP001 不再拦截空单元格",
        "if any(c == \"\" for c in cells):",
        "if False:  # MUTANT",
    ),
    (
        "FM001 不再核对 frontmatter 必填",
        "missing = [k for k in REQUIRED_FM if k not in fm or not fm[k]]",
        "missing = []  # MUTANT",
    ),
]


def run_selftest() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(SELFTEST)], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, (p.stdout + p.stderr)


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    caught: list[str] = []
    escaped: list[str] = []
    try:
        for name, old, new in MUTATIONS:
            if old not in original:
                escaped.append(f"{name} —— ⚠️ 定位失败：原片段已不在源码中（变异可能失效）")
                continue
            TARGET.write_text(original.replace(old, new, 1), encoding="utf-8")
            code, out = run_selftest()
            if code != 0:
                first = next((l.strip() for l in out.splitlines() if l.strip().startswith("✗")), "")
                caught.append(f"{name} → 自审变红{'（' + first.lstrip('✗ ')[:52] + '）' if first else ''}")
            else:
                escaped.append(f"{name} → ❌ 自审仍全绿，该处判定无人守护")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    print("变异测试：逐处破坏判定逻辑，检查自审套件是否会红\n" + "=" * 62)
    for m in caught:
        print(f"  ✓ {m}")
    if escaped:
        print(f"\n❌ 逃逸 {len(escaped)} 处")
        for m in escaped:
            print(f"  ✗ {m}")
        print("\n逃逸意味着：对应检查的负向用例是空断言，删掉被测代码它照样通过。")
        return 1
    print(f"\n✅ {len(caught)}/{len(MUTATIONS)} 处变异全部被自审捕获——自审不是空转")
    return 0


if __name__ == "__main__":
    sys.exit(main())
