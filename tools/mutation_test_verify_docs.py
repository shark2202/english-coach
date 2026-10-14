#!/usr/bin/env python3
"""校验器变异测试（R5 的准入条件）。

为什么需要它：二轮 L2 用变异测试证明，`tools/selftest_verify_docs.py`
当时有 3 个用例是**空断言**——把被测代码整段删掉，用例照样打 ✓。
换句话说，那套自审在为一扇它从未推开过的门背书。

**自审套件证明检查会在坏输入上触发；变异测试证明自审本身不是空转。**

三轮 L2 又指出本文件自身的三处缺陷，本版已逐条修正：

1. **原地改写被跟踪源码**（旧版）→ 新版把 `tools/` 与契约复制进 `/tmp` 沙箱再变异，
   **全程不碰仓库文件**。旧版若被 SIGKILL，会给仓库留下永久损坏的门禁，
   而 `AGENTS.md` 却要求每个 agent 直接执行它。
2. **崩溃冒充捕获**（旧版只看 returncode != 0）→ 新版必须看到自审输出
   「门禁失灵」标记才算捕获；带 Traceback 或 0 条用例执行的崩溃一律记为**逃逸**。
3. **变异点定位失败被静默跳过** → 旧版把「定位失败」与「逃逸」混记，
   现分为两类并分别计数。

用法：
    python3 tools/mutation_test_verify_docs.py
退出码：0 = 每处变异都被自审捕获；1 = 有变异逃逸（自审存在空断言）
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAUGHT_MARK = "门禁失灵"

# (变异名, 原片段, 替换片段)——每一条都必须指向一段「承担判定」的代码。
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
        "elif declared != actual:",
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
        'for f in sorted(REQ_DIR.glob("*.md")):',
        "for f in []:  # MUTANT",
    ),
    (
        "EMP001 不再拦截空单元格",
        'if any(c == "" for c in cells):',
        "if False:  # MUTANT",
    ),
    (
        "FM001 不再核对 frontmatter 必填",
        "missing = [k for k in REQUIRED_FM if k not in fm or not fm[k]]",
        "missing = []  # MUTANT",
    ),
    (
        "ST001 不再检测陈旧表述",
        "if re.search(pat, text):",
        "if False:  # MUTANT",
    ),
    (
        "LK001 不再检测悬空链接",
        "if not resolved.exists():",
        "if False:  # MUTANT",
    ),
    (
        "HF001 不再检测草稿谎报",
        'if "草稿" in status:',
        "if False:  # MUTANT",
    ),
    (
        # 这一处关闭会让 compare() 的比较分支失效。门禁本身仍会打印
        # 「✓ 与声明一致」——因为任何代码都可被变异，结构性防御不存在；
        # 真正的防线是自审套件的负例（本行即其存在理由）。
        "CNT001–005 的声明比较被关闭（波及五个码）",
        "elif int(decl.group(1)) != actual:",
        "elif False:  # MUTANT",
    ),
    (
        "MAN003 锁文件校验恒为真（洗白路径）",
        "if locked != cur:",
        "if False:  # MUTANT",
    ),
    (
        "FM000 不再报告缺 frontmatter",
        "if not fm:",
        "if False:  # MUTANT",
    ),
    (
        "HF002 不再告警状态自相矛盾",
        'if "已冻结" in status and "待" in status:',
        "if False:  # MUTANT",
    ),
    (
        "ST002 不再告警状态表缺事件表",
        "if n_matrices and n_legends < n_matrices:",
        "if False:  # MUTANT",
    ),
    (
        "MAN000 不再告警清单缺失",
        "if not MANIFEST.exists():",
        "if False:  # MUTANT",
    ),
    (
        "CNT006 定点声明比对恒为真",
        "if declared_n != actual_n:",
        "if False:  # MUTANT",
    ),
    (
        "OWN000 不再告警契约缺失",
        "if not CONTRACT.exists():",
        "if False:  # MUTANT",
    ),
    (
        "FIX000 不再告警台账为空",
        "if not fixes:",
        "if False:  # MUTANT",
    ),
    (
        "RM000 不再告警 README 缺失",
        "if not readme.exists():",
        "if False:  # MUTANT",
    ),
    (
        "FIX002 不再校验证据定义",
        'if kind not in ("contains", "not_contains") or not needle:',
        "if False:  # MUTANT",
    ),
    (
        "OWN002 反向检查失效",
        "def check_contract_covers_all(own: dict[str, str]) -> None:\n    \"\"\"反向：docs/requirements 下每个文件都必须在契约中被 owns。\"\"\"\n    if not own:",
        "def check_contract_covers_all(own: dict[str, str]) -> None:\n    \"\"\"反向：docs/requirements 下每个文件都必须在契约中被 owns。\"\"\"\n    if True:  # MUTANT",
    ),
]


def build_sandbox(dst: Path) -> Path:
    """复制校验器、自审与契约到沙箱。selftest 的 ROOT 由自身路径推导，
    因此放在 <sandbox>/tools/ 下时，它加载的就是沙箱里的副本。"""
    (dst / "tools").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "tools" / "verify_docs.py", dst / "tools" / "verify_docs.py")
    shutil.copy2(ROOT / "tools" / "selftest_verify_docs.py", dst / "tools" / "selftest_verify_docs.py")
    contracts = dst / "docs" / "swarm" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "docs" / "swarm" / "contracts").glob("*.json"):
        shutil.copy2(f, contracts / f.name)
    return dst / "tools" / "selftest_verify_docs.py"


def main() -> int:
    original = (ROOT / "tools" / "verify_docs.py").read_text(encoding="utf-8")
    caught: list[str] = []
    escaped: list[str] = []
    mislocated: list[str] = []

    for name, old, new in MUTATIONS:
        # 定位守护：目标片段必须**恰好出现一次**。
        # 三轮 L2 指出 replace(old,new,1) 只改第一处、命中哪处取决于函数顺序，
        # 且无断言守护——实测中「CNT006 定点声明」这一变异实际改到了
        # check_ownership 里同名的那一行，标签正确、位置错误，等于没测。
        n = original.count(old)
        if n != 1:
            mislocated.append(
                f"{name} —— 定位失败：目标片段在源码中出现 {n} 次（应为 1），变异可能打错位置")
            continue
        with tempfile.TemporaryDirectory(prefix="vd-mut-") as td:
            sb = Path(td)
            st = build_sandbox(sb)
            (sb / "tools" / "verify_docs.py").write_text(
                original.replace(old, new, 1), encoding="utf-8")
            p = subprocess.run([sys.executable, str(st)], capture_output=True,
                               text=True, cwd=sb, timeout=300)
            out = p.stdout + p.stderr

        crashed = p.returncode != 0 and CAUGHT_MARK not in out
        if p.returncode == 0:
            escaped.append(f"{name} → 自审仍全绿，该处判定无人守护")
        elif crashed:
            escaped.append(f"{name} → 自审崩溃而非断言失败，崩溃不得冒充捕获")
        else:
            first = next((l.strip() for l in out.splitlines()
                          if l.strip().startswith("✗")), "")
            caught.append(f"{name} → 自审变红（{first.lstrip('✗ ')[:46]}）")

    # 沙箱法的前提是仓库文件不受影响——这是本版最重要的自证
    assert (ROOT / "tools" / "verify_docs.py").read_text(encoding="utf-8") == original, \
        "变异过程污染了仓库源码"

    print("变异测试：逐处破坏判定逻辑，检查自审套件是否会红\n" + "=" * 66)
    print("方法：复制到 /tmp 沙箱后再变异——全程不改写仓库源码（崩溃不会留下损坏的门禁）")
    print("判定：必须看到「门禁失灵」标记才算捕获；崩溃一律记为逃逸\n")
    for m in caught:
        print(f"  ✓ {m}")
    for m in mislocated:
        print(f"  ⚠ {m}")
    if escaped:
        print(f"\n❌ 逃逸 {len(escaped)} 处")
        for m in escaped:
            print(f"  ✗ {m}")
        print("\n逃逸意味着：对应检查的负向用例是空断言，删掉被测代码它照样通过。")
        return 1
    if mislocated:
        print(f"\n❌ 有 {len(mislocated)} 处变异定位失败——覆盖矩阵已失效，须同步更新")
        return 1
    print(f"\n✅ {len(caught)}/{len(MUTATIONS)} 处变异全部被自审捕获，且仓库源码零污染")
    return 0


if __name__ == "__main__":
    sys.exit(main())