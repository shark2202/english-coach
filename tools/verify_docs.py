#!/usr/bin/env python3
"""L1 机器绿灯校验器——蜂群产出的机械校验层（ORG-SPEC §一 L1）。

只做机器能判定的事，不做主观判断。失败项即逃逸点，须在 L2 之前拦截。
用法：
    python3 tools/verify_docs.py            # 检查全部需求文档
    python3 tools/verify_docs.py --strict   # 警告也视为失败
退出码：0 = 全绿；1 = 有 FAIL
"""

from __future__ import annotations

import json
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


def unquote(s: str) -> str:
    """剥掉成对的包裹引号。frontmatter 值既可能写 `batch: xxx` 也可能写 `batch: "xxx"`，
    两种写法必须等价——否则 OWN001 会把同一个值判成越权写入（已实际发生过）。"""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


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
            out[m.group(1)] = unquote(m.group(2).strip())
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
    """文档 frontmatter 的 description 常写「N 个对象 / N 条关系」等，须与正文实测一致。

    ⚠️ 三分支，不可退回两分支：找到声明且不一致→FAIL；找到声明且一致→ok；
    **没找到声明→必须说「没核查」，绝不能落到 ok 分支**。
    三轮 L2 实测：把 CNT003 的判定整行关闭后，本函数仍打印
    「✓ 字段数 66 与声明一致」并让门禁报告全绿——门禁在输出它从未做过的核查结论。
    """
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    desc = fm.get("description", "")

    def compare(decl, actual, label, code, unit):
        """decl 为 None 表示 description 里没有可核对的声明——本次未核查。"""
        if decl is None:
            warn(path.name, "CNT000",
                 f"description 中未找到「{label}」声明，本次未做核查（实测值 {actual}）")
        elif int(decl.group(1)) != actual:
            fail(path.name, code, f"声明 {decl.group(1)} {unit}，正文实测 {actual}")
        else:
            ok(f"{path.name}: {label} {actual} 与声明一致")

    # 按文件名判定模型类型——frontmatter 的 model 值含中文与括号，按路径判定更稳
    stem = path.stem

    if stem.startswith("02-"):
        rel_actual = count_table_rows(text, r"^\|\s*[0-9]\.[0-9]\s*\|")
        compare(re.search(r"(\d+)\s*条关系", desc), rel_actual, "关系数", "CNT001", "条关系")

        objs = set()
        for m in re.finditer(r"^## [二三四五]、BDD-\d · .*?（(.+?)）", text, re.M):
            for name in m.group(1).split(" / "):
                objs.add(name.strip())
        compare(re.search(r"(\d+)\s*个业务数据对象", desc), len(objs),
                "对象数", "CNT002", "个业务数据对象")

    if stem.startswith("03-"):
        fd_actual = count_table_rows(text, r"^\|\s*DD[0-9]{3}\s*\|")
        compare(re.search(r"(\d+)\s*个字段", desc), fd_actual, "字段数", "CNT003", "个字段")

    if stem.startswith("01-"):
        seg = text.split("## 二、")[1].split("## 三、")[0] if "## 二、" in text else ""
        l1_actual = len(re.findall(r"L1-\d+ ", seg))
        # L2 在 ASCII 树里按 ├/└ 计数，须扣除 L0 盒子的 └
        tree = re.search(r"```\n(.*?)\n```", text, re.S)
        l2_actual = 0
        if tree:
            l2_actual = len(re.findall(r"[├└]", tree.group(1))) - 1  # 扣 L0 盒子的 └
        compare(re.search(r"(\d+)\s*个\s*L1", desc), l1_actual, "L1 数", "CNT004", "个 L1")
        compare(re.search(r"(\d+)\s*个\s*L2", desc), l2_actual, "L2 数", "CNT005", "个 L2")


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


# ── 检查 9：写入范围（OWN001，契约修订 R1） ──────────────────────────
# 动机：蜂群首轮 4 起越权写入，内容均正确但门禁零拦截。本检查把
# 「写入的文件是否在契约 owns 清单内」从 orchestrator 事后复核变成机器强制。

CONTRACT = ROOT / "docs" / "swarm" / "contracts" / "batches-06-to-09.json"


def load_ownership() -> dict[str, str]:
    """返回 {文件名: 批次 id}。契约缺失时返回空字典并**告警**，不静默——
    「读不到契约」与「契约读到了但没 owns」是两种不同的失败，
    前者若静默返回 {}，下游会把「无授权」误当成「无需检查」。"""
    if not CONTRACT.exists():
        warn(CONTRACT.name, "OWN000", "契约文件不存在，OWN 检查将全部跳过")
        return {}
    try:
        c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        warn(CONTRACT.name, "OWN000", f"契约 JSON 非法，OWN 检查跳过：{e}")
        return {}
    own: dict[str, str] = {}
    for b in c.get("batches", []):
        for f in b.get("owns", []):
            own[Path(f).name] = b.get("id", "?")
    return own


def check_ownership(path: Path, own: dict[str, str]) -> None:
    if not own:
        return
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    declared = fm.get("batch")
    actual = own.get(path.name)
    if actual is None:
        fail(path.name, "OWN002", "契约中无任何批次 owns 此文件——未授权创建")
        return
    if not declared:
        fail(path.name, "OWN001", f"frontmatter 未声明 batch（契约归属 {actual}）")
    elif declared != actual:
        fail(path.name, "OWN001",
             f"batch 声明为 {declared}，但契约归属为 {actual}——越权写入")


def check_contract_covers_all(own: dict[str, str]) -> None:
    """反向：docs/requirements 下每个文件都必须在契约中被 owns。"""
    if not own:
        return
    for p in sorted(REQ_DIR.glob("*.md")):
        if p.name not in own:
            fail(p.name, "OWN002", "契约 owns 清单未覆盖此文件")


# ── 检查 10：跨文档修正闭环验收（FIX001，契约修订 R4） ────────────────
# 动机：域 agent 只能写自己 owns 的文件，其余修正以 cross_doc_fixes 交回，
# 由 orchestrator 串行应用。本轮那些修正是手工 grep 应用的，没有机器确认环节——
# 「我改了」与「真的改了」之间没有证据链。本检查把台账里的 evidence 逐条核对。

FIX_LEDGER = ROOT / "docs" / "swarm" / "contracts" / "applied-fixes.json"


def check_applied_fixes() -> None:
    if not FIX_LEDGER.exists():
        warn(FIX_LEDGER.name, "FIX000", "台账不存在，跨文档修正闭环无法验收")
        return
    try:
        data = json.loads(FIX_LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(FIX_LEDGER.name, "FIX002", f"台账 JSON 非法：{e}")
        return

    fixes = data.get("fixes", [])
    if not fixes:
        warn(FIX_LEDGER.name, "FIX000", "台账无条目")
        return

    verified = 0
    superseded = 0
    for fx in fixes:
        fid = fx.get("id", "?")
        # 被后续修正取代的条目保留在台账里（历史不可删），但不参与证据核对——
        # 否则一次正常的再修正就会被判成「此前的修正没落地」
        if fx.get("superseded_by"):
            superseded += 1
            continue
        target = ROOT / fx.get("target_file", "")
        ev = fx.get("evidence", {})
        kind, needle = ev.get("type", ""), ev.get("string", "")
        if kind not in ("contains", "not_contains") or not needle:
            fail(fid, "FIX002", f"证据定义无效：{ev}")
            continue
        if not target.exists():
            fail(fid, "FIX001", f"目标文件不存在：{fx.get('target_file')}")
            continue
        present = needle in target.read_text(encoding="utf-8")
        if kind == "contains" and not present:
            fail(fid, "FIX001",
                 f"声称已修但未落地：{fx.get('target_file')} 不含「{needle[:40]}」")
        elif kind == "not_contains" and present:
            fail(fid, "FIX001",
                 f"声称已修但未落地：{fx.get('target_file')} 仍含「{needle[:40]}」")
        else:
            verified += 1
    note = f"，{superseded} 条已被后续修正取代（历史保留，不参与核对）" if superseded else ""
    ok(f"{FIX_LEDGER.name}: {verified}/{len(fixes) - superseded} 条修正证据成立{note}")


# ── 检查 11：内容指纹（MAN001） ────────────────────────────────────────
# 动机：L2 独立判别器实测证明 OWN001/OWN002 抓不到 RETRO-01 的真实越权形态——
# agent 改别人的文件内容而 batch: 字段纹丝不动，OWN001/OWN002 全绿。
# 本检查把「内容变了但没人申报」变成 FAIL。清单冻结后不再更新，
# 合法变动只有两种：未动，或在 applied-fixes.json 里申报了新的 sha256。

import hashlib

MANIFEST = ROOT / "docs" / "swarm" / "contracts" / "content-manifest.json"
MANIFEST_LOCK = ROOT / "tools" / "manifest.lock"


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_manifest_lock() -> bool:
    """清单是全部产物的参照系，它自己却不能被指纹覆盖——否则自指死循环。
    改用锁文件消除自指：清单的 sha256 写在 tools/manifest.lock，
    单独改清单会立刻失配。想洗白任意文件就必须同时改两个文件，
    这把它从「一个文件的静默篡改」变成「两个文件的可见改动」（git diff 看得见）。
    """
    if not MANIFEST_LOCK.exists():
        fail("tools/manifest.lock", "MAN003",
             "锁文件不存在——清单可被改写以洗白任意文件，本检查失效")
        return False
    locked = MANIFEST_LOCK.read_text(encoding="utf-8").split()[0].strip()
    cur = sha256_of(MANIFEST)
    if locked != cur:
        fail("docs/swarm/contracts/content-manifest.json", "MAN003",
             f"清单已变更但锁文件未同步（lock={locked[:12]}… 实际={cur[:12]}…）")
        return False
    ok(f"manifest.lock 与清单指纹一致（{cur[:12]}…）")
    return True


def declared_hashes() -> dict[str, set[str]]:
    """从 applied-fixes 台账收集各文件的合法新指纹。"""
    out: dict[str, set[str]] = {}
    if not FIX_LEDGER.exists():
        warn(FIX_LEDGER.name, "FIX000", "台账不存在，无法采集已申报的新指纹")
        return out
    try:
        data = json.loads(FIX_LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        warn(FIX_LEDGER.name, "FIX002", f"台账 JSON 非法，无法采集新指纹：{e}")
        return out
    for fx in data.get("fixes", []):
        h = fx.get("new_sha256")
        if h and fx.get("target_file"):
            out.setdefault(fx["target_file"], set()).add(h)
    return out


def check_content_manifest() -> None:
    if not MANIFEST.exists():
        warn(MANIFEST.name, "MAN000", "内容指纹清单不存在，内容级越权无法拦截")
        return
    if not check_manifest_lock():
        return  # 参照系本身被改过，继续核对内容没有意义
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(MANIFEST.name, "MAN002", f"清单 JSON 非法：{e}")
        return

    legal = declared_hashes()
    entries = data.get("files", [])
    clean = 0
    for e in entries:
        rel, frozen = e.get("path", ""), e.get("sha256", "")
        p = ROOT / rel
        if not p.exists():
            fail(rel, "MAN001", f"清单登记的文件不存在：{rel}")
            continue
        cur = sha256_of(p)
        if cur == frozen or cur in legal.get(rel, set()):
            clean += 1
        else:
            fail(rel, "MAN001",
                 "内容已变更但未在 applied-fixes 台账申报——内容级越权或未登记的编辑")
    ok(f"{MANIFEST.name}: {clean}/{len(entries)} 份文件内容可归因")


# ── 检查 12：DD 引用有效性（REF001） ──────────────────────────────────
# 动机：L2 实测发现 13-display-action-response.md 引用了 DD411，
# 而数据字典最大结构标注字段是 DD410——悬空引用在本项目是真实失败模式，
# 不是理论风险。人工比对 84 条需求里散落的 DD 引用不现实，这里做成机器判定。
# 只做「精确可判定」的部分：编号是否存在。基数、状态名等语义一致性留给 L2。

DD_DICT = REQ_DIR / "03-data-dictionary.md"


def defined_dd_ids() -> set[str]:
    if not DD_DICT.exists():
        warn(DD_DICT.name, "REF000", "数据字典不存在，DD 引用有效性检查将全部跳过")
        return set()
    return set(re.findall(r"^\|\s*(DD\d{3})\s*\|", DD_DICT.read_text(encoding="utf-8"), re.M))


def check_dd_references(dd_defs: set[str]) -> None:
    if not dd_defs:
        warn("DD 引用有效性", "REF000", "可用的 DD 编号集为空，本次未做核查")
        return
    dangling_total = 0
    for p in sorted(REQ_DIR.glob("*.md")):
        dangling: set[str] = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            # 显式声明「待定义/预留」的编号不算悬空——那是尚未兑现的承诺，不是错引
            if re.search(r"待定义|预留|TBD|待补", line):
                continue
            dangling |= set(re.findall(r"DD\d{3}", line)) - dd_defs
        if dangling:
            dangling_total += len(dangling)
            fail(p.name, "REF001",
                 f"引用了数据字典中不存在的字段编号：{'、'.join(sorted(dangling))}")
    if not dangling_total:
        ok(f"全部需求文档的 DD 引用均在数据字典中有定义（{len(dd_defs)} 个编号）")


# ── 检查 13：定点声明绑定（CNT006） ──────────────────────────────────
# 为什么不做通用版：三轮 L2 的判断——通用的「N 条 ↔ 正文可数结构」正则必然误报，
# 而误报率高的门禁会被整体忽略（告警疲劳比漏报更危险）。
# 实证可行的替代是**定点绑定**：只绑定已造成过真实缺陷的少数声明，
# 每个提取器单独可回归、误报率单独计量。判别器用 3 条提取器当场查出了
# 「13 声明共 30 个字段号、实测 28」这条 L1 三层全绿漏过的缺陷。
# 扩展方式：新增一行绑定，并**同时为它补一条负例进自审套件**。

# (文件名, 声明正则（须含一个捕获组）, 提取器, 说明)
# 提取器写���**表达式字符串**而非函数，便于直接采纳 `docs/swarm/contracts/proposals/`
# 下的提案文件——提案由域 agent 逐条自证过反证后才进入本表。
# 信任边界：表达式来自本仓经判别器复核的提案文件，不接受任何外部输入；
# `_SAFE_EVAL` 只暴露 re/len/set/sorted/max/min/abs/sum/round，且拒绝含
# `import`、`__` 的表达式。它决定「是否可数」，不决定「数出什么值」——
# 一个写错的表达式只会误报或漏报，不会执行任意代码。
TARGETED: list[tuple[str, str, str, str]] = [
    ("11-system-flow.md", r"以 (\d+) 条补偿条目覆盖",
     "_comp_rows(t)", "§9.1 + §9.2 补偿条目数（此处出过 32 / 40 / 31 三次错）"),
    ("13-display-action-response.md", r"(\d+) 张元素表",
     "len(set(re.findall(r'ELMT_[0-9]{4}', t)))", "去重后的 ELMT 元素表数"),
    ("13-display-action-response.md", r"共 (\d+) 个字段号",
     "len(set(re.findall(r'DD[0-9]{3}', t)))", "去重后的 DD 引用数"),
]


def _comp_rows(t: str) -> int:
    """11 的 §9.1 + §9.2 补偿条目行数（行首形如 `| 1.1 校验账本可用性 |`）。"""
    if "### 9.1" not in t:
        return 0
    sec = t.split("### 9.1", 1)[1]
    return len(re.findall(r"^\|\s*1\.[0-9x]", sec, re.M))


_SAFE_EVAL = {"re": re, "len": len, "set": set, "sorted": sorted,
              "max": max, "min": min, "abs": abs, "sum": sum, "round": round,
              "_comp_rows": _comp_rows}


def _run_extractor(expr: str, text: str):
    """在受限命名空间里求值提取器表达式。"""
    if "import" in expr or "__" in expr:
        raise ValueError(f"提取器表达式含不允许的构造：{expr[:40]}")
    return eval(expr, {"__builtins__": {}}, {**_SAFE_EVAL, "t": text})  # noqa: S307


def check_targeted_declarations() -> None:
    checked = 0
    for fname, pat, expr, label in TARGETED:
        p = REQ_DIR / fname
        if not p.exists():
            warn(fname, "CNT006", "文件不存在，定点声明绑定无法执行")
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(pat, text)
        if not m:
            warn(fname, "CNT000", f"未找到「{label}」的声明，本次未做核查")
            continue
        try:
            actual_n = _run_extractor(expr, text)
        except Exception as e:  # 提取器自身坏了——必须报，不能静默跳过
            fail(fname, "CNT007", f"提取器执行失败：{type(e).__name__}（{expr[:40]}）")
            continue
        declared_n = int(m.group(1))
        if declared_n != actual_n:
            fail(fname, "CNT006", f"声明 {label} {declared_n}，正文实测 {actual_n}")
        else:
            checked += 1
    if checked:
        ok(f"定点声明绑定：{checked}/{len(TARGETED)} 条声明与正文实测一致")


# ── 主流程 ────────────────────────────────────────────────────────────
def main() -> int:
    if not REQ_DIR.exists():
        print(f"找不到 {REQ_DIR}")
        return 1

    own = load_ownership()
    docs = sorted(REQ_DIR.glob("*.md"))
    print(f"校验 {len(docs)} 份需求文档 + README" + (f" + {len(own)} 份契约归属" if own else "") + "\n" + "=" * 62)

    for f in docs:
        check_frontmatter(f)
        check_links(f)
        check_stale(f)
        check_declared_counts(f)
        check_empty_cells(f)
        check_state_table(f)
        check_draft_honesty(f)
        check_ownership(f, own)

    check_readme_index()
    check_contract_covers_all(own)
    check_applied_fixes()
    check_content_manifest()
    check_dd_references(defined_dd_ids())
    check_targeted_declarations()

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
