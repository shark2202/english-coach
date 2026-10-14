#!/usr/bin/env python3
"""L1 机器绿灯校验器——蜂群产出的机械校验层（ORG-SPEC §一 L1）。

只做机器能判定的事，不做主观判断。失败项即逃逸点，须在 L2 之前拦截。
用法：
    python3 tools/verify_docs.py            # 检查全部需求文档
    python3 tools/verify_docs.py --strict   # 警告也视为失败
退出码：0 = 全绿；1 = 有 FAIL
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ_DIR = ROOT / "docs" / "requirements"

FAIL: list[str] = []
WARN: list[str] = []
OK: list[str] = []


def fail(f: str, code: str, detail: str = "") -> None:
    FAIL.append(f"[{code}] {f}" + (f" — {detail}" if detail else ""))


def warn(f: str, code: str, detail: str = "") -> None:
    WARN.append(f"[{code}] {f}" + (f" — {detail}" if detail else ""))


def ok(msg: str) -> None:
    OK.append(msg)


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


# ── 检查 1：frontmatter 必填字段 ──────────────────────────────────────
REQUIRED_FM = ["type", "title", "description", "status"]


def check_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if not fm:
        fail(path.name, "FM000", "缺少 frontmatter")
        return {}
    missing = [k for k in REQUIRED_FM if k not in fm or not fm[k]]
    if missing:
        fail(path.name, "FM001", f"缺必填字段：{', '.join(missing)}")
    return fm


# ── 检查 2：内部链接可解析 ────────────────────────────────────────────
def check_links(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    base = path.parent
    for label, target in re.findall(r"\[([^\]]*)\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        clean = target.split("#")[0]
        if not clean:
            continue
        resolved = (base / clean).resolve()
        if not resolved.exists():
            fail(path.name, "LK001", f"链接不存在：[{label}]({target})")


# ── 检查 3：陈旧表述检测（目标重锚前遗留） ────────────────────────────
STALE = [
    (r"五平台路线", "已改为「Ubuntu 延后或取消」"),
    (r"不替代\s*Flutter\s*主选", "已被 v0.3 裁决推翻"),
    (r"app-design\.md\]\(.*\)\s*——\s*App 设计.*v0\.2", "app-design 已升 v0.3"),
]


def check_stale(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pat, why in STALE:
        if re.search(pat, text):
            fail(path.name, "ST001", f"陈旧表述 /{pat}/ — {why}")


# ── 检查 4：声明计数 vs 实际计数 ──────────────────────────────────────
def width(s: str) -> int:
    """按终端显示宽度计算（CJK 占 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def strip_pad(s: str) -> str:
    return s.strip()


def count_table_rows(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text, re.M))


def check_declared_counts(path: Path) -> None:
    """文档 frontmatter 的 description 常写「N 个对象 / N 条关系」等，须与正文实测一致。"""
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    desc = fm.get("description", "")

    # 按文件名判定模型类型——frontmatter 的 model 值含中文与括号，按路径判定更稳
    stem = path.stem

    if stem.startswith("02-"):
        rel_decl = re.search(r"(\d+)\s*条关系", desc)
        rel_actual = count_table_rows(text, r"^\|\s*[0-9]\.[0-9]\s*\|")
        if rel_decl and int(rel_decl.group(1)) != rel_actual:
            fail(path.name, "CNT001",
                 f"声明 {rel_decl.group(1)} 条关系，正文实测 {rel_actual} 条")
        else:
            ok(f"{path.name}: 关系数 {rel_actual} 与声明一致")

        obj_decl = re.search(r"(\d+)\s*个业务数据对象", desc)
        objs = set()
        for m in re.finditer(r"^## [二三四五]、BDD-\d · .*?（(.+?)）", text, re.M):
            for name in m.group(1).split(" / "):
                objs.add(name.strip())
        if obj_decl and int(obj_decl.group(1)) != len(objs):
            fail(path.name, "CNT002",
                 f"声明 {obj_decl.group(1)} 个对象，各域标题实测 {len(objs)} 个")
        else:
            ok(f"{path.name}: 对象数 {len(objs)} 与声明一致")

    if stem.startswith("03-"):
        fd_decl = re.search(r"(\d+)\s*个字段", desc)
        fd_actual = count_table_rows(text, r"^\|\s*DD[0-9]{3}\s*\|")
        if fd_decl and int(fd_decl.group(1)) != fd_actual:
            fail(path.name, "CNT003",
                 f"声明 {fd_decl.group(1)} 个字段，正文实测 {fd_actual} 个")
        else:
            ok(f"{path.name}: 字段数 {fd_actual} 与声明一致")

    if stem.startswith("01-"):
        l1_decl = re.search(r"(\d+)\s*个\s*L1", desc)
        l2_decl = re.search(r"(\d+)\s*个\s*L2", desc)
        seg = text.split("## 二、")[1].split("## 三、")[0] if "## 二、" in text else ""
        l1_actual = len(re.findall(r"L1-\d+ ", seg))
        # L2 在 ASCII 树里按 ├/└ 计数，须扣除 L0 盒子的 └
        tree = re.search(r"```\n(.*?)\n```", text, re.S)
        l2_actual = 0
        if tree:
            glyphs = len(re.findall(r"[├└]", tree.group(1)))
            l2_actual = glyphs - 1  # 扣 L0 盒子的 └
        if l1_decl and int(l1_decl.group(1)) != l1_actual:
            fail(path.name, "CNT004",
                 f"声明 {l1_decl.group(1)} 个 L1，§二 实测 {l1_actual} 个")
        else:
            ok(f"{path.name}: L1 数 {l1_actual} 与声明一致")
        if l2_decl and int(l2_decl.group(1)) != l2_actual:
            fail(path.name, "CNT005",
                 f"声明 {l2_decl.group(1)} 个 L2，树形图实测 {l2_actual} 个")
        else:
            ok(f"{path.name}: L2 数 {l2_actual} 与声明一致")


# ── 检查 5：表格无空单元格（必填区） ──────────────────────────────────
EMPTY_CELL = re.compile(r"\|\s*\|\s*\|")


def check_empty_cells(path: Path) -> None:
    """字段表（DD 行）与关系表不得有空单元格——卡内明确「不留空白」。"""
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if re.match(r"^\|\s*(DD[0-9]{3}|[0-9]\.[0-9])\s*\|", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any(c == "" for c in cells):
                fail(path.name, "EMP001", f"第 {i} 行有空单元格：{line[:60]}")


# ── 检查 6：状态表「无」格须有理由 ────────────────────────────────────
def check_state_table(path: Path) -> None:
    """状态表的每张 N×N 矩阵，表头首格为「初 ＼ 标」；矩阵数须与事件解释表数一致。"""
    if not path.stem.startswith("04-"):
        return
    text = path.read_text(encoding="utf-8")
    n_matrices = text.count("| 初 ＼ 标 |")
    n_legends = text.count("| 代号 | 触发事件")
    if n_matrices and n_legends < n_matrices:
        warn(path.name, "ST002",
             f"{n_matrices} 张 N×N 状态表但仅 {n_legends} 个事件解释表")
    else:
        ok(f"{path.name}: {n_matrices} 张状态表与 {n_legends} 个事件表匹配")


# ── 检查 7：文档不得自称「定稿」而带未完成校验 ────────────────────────
def check_draft_honesty(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    status = fm.get("status", "")
    if "草稿" in status:
        if re.search(r"已完成交叉校验|完备性校验通过", text):
            fail(path.name, "HF001", "status 为草稿但正文声称校验通过")
    if "已冻结" in status and "待" in status:
        warn(path.name, "HF002", f"status 同时含「已冻结」与「待」：{status[:60]}")


# ── 检查 8：README 索引完整性 ──────────────────────────────────────────
def check_readme_index() -> None:
    readme = ROOT / "README.md"
    if not readme.exists():
        warn("README.md", "RM000", "不存在")
        return
    text = readme.read_text(encoding="utf-8")
    for f in sorted(REQ_DIR.glob("*.md")):
        if f.name not in text:
            fail("README.md", "RM001", f"未在 README 索引中登记：{f.name}")


# ── 主流程 ────────────────────────────────────────────────────────────
def main() -> int:
    if not REQ_DIR.exists():
        print(f"找不到 {REQ_DIR}")
        return 1

    docs = sorted(REQ_DIR.glob("*.md"))
    print(f"校验 {len(docs)} 份需求文档 + README\n" + "=" * 62)

    for f in docs:
        check_frontmatter(f)
        check_links(f)
        check_stale(f)
        check_declared_counts(f)
        check_empty_cells(f)
        check_state_table(f)
        check_draft_honesty(f)

    check_readme_index()

    print(f"PASS {len(OK)}")
    for m in OK:
        print(f"  ✓ {m}")

    if WARN:
        print(f"\nWARN {len(WARN)}")
        for m in WARN:
            print(f"  ! {m}")

    if FAIL:
        print(f"\nFAIL {len(FAIL)}")
        for m in FAIL:
            print(f"  ✗ {m}")
        return 1

    print("\n✅ 全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
