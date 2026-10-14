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
# 「本次未核查」与「核查通过」必须走两条通道。三轮 L2 打出的同一个根因：
# `else: ok()` 把「没查」渲染成「查过且没事」。删掉整节时声明随之消失，
# 门禁只留一句 CNT000 告警便退出 0——一份被掏空的文档被判为全绿。
# 实测复现：把 10-data-flow-diagram.md 的「## 二、确定流程」整节清空，
# FAIL=0、退出码 0。故 UNCHECKED 独立计数并直接决定退出码。
UNCHECKED: list[str] = []
OK: list[str] = []


def fail(f: str, code: str, detail: str = "") -> None:
    FAIL.append(f"[{code}] {f}" + (f" — {detail}" if detail else ""))


def warn(f: str, code: str, detail: str = "") -> None:
    WARN.append(f"[{code}] {f}" + (f" — {detail}" if detail else ""))


def unchecked(f: str, code: str, detail: str = "") -> None:
    """本次没有核查——不是「核查通过」，也不是「核查不通过」。

    它同时进 WARN（供人读）与 UNCHECKED（供退出码用）。凡此调用都意味着
    门禁对这份文档**无法背书**，故默认运行也必须非零退出；只有把整条
    检查显式关掉才能归零——不能靠「没找到声明」自动放行。
    """
    msg = f"[{code}] {f}" + (f" — {detail}" if detail else "")
    WARN.append(msg)
    UNCHECKED.append(msg)


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
            unchecked(path.name, "CNT000",
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
        # evidence 支持**断言数组**：一条修正既要证明「新内容已落地」，
        # 也要证明「被替换掉的旧假声明已消失」。L2 四轮实测单条断言的缺口——
        # 只要 new_sha256 填对，拿一个必然存在的串（如新增小标题）就能让
        # MAN001 与 FIX001 全部放行，旧声明是否还在无人验证。子 agent 当时
        # 只能在正向与负向之间二选一，并把换下的断言写进人工 note 披露。
        # 数组让两者同时进机器核对，note 只负责机器确实覆盖不到的部分。
        ev = fx.get("evidence", {})
        evs = ev if isinstance(ev, list) else [ev]
        if not evs:
            fail(fid, "FIX002", f"证据定义无效：{fx.get('evidence')!r}（空列表）")
            continue
        bad = [e for e in evs
               if not isinstance(e, dict)
               or e.get("type") not in ("contains", "not_contains")
               or not e.get("string")]
        if bad:
            fail(fid, "FIX002", f"证据定义无效：{bad[0]}")
            continue
        if not target.exists():
            fail(fid, "FIX001", f"目标文件不存在：{fx.get('target_file')}")
            continue
        body = target.read_text(encoding="utf-8")
        missed = []
        for e in evs:
            present = e["string"] in body
            if (e["type"] == "contains" and not present) or \
               (e["type"] == "not_contains" and present):
                missed.append(("缺少" if e["type"] == "contains" else "仍含")
                              + f"「{e['string'][:40]}」")
        if missed:
            fail(fid, "FIX001",
                 f"声称已修但未落地：{fx.get('target_file')} " + "；".join(missed))
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
        # 已被后续修正取代的历史条目**不得再授权**。L2 四轮实测：只保留一条
        # 带 superseded_by 的条目，其 new_sha256 仍被采信，MAN001 因此放行——
        # 也就是说「作废声明」本身可以被用来洗白。台账保留历史是为了记录发生过
        # 什么，但授权只属于仍然生效的那一条。
        if fx.get("superseded_by"):
            continue
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
# ── 来自 docs/swarm/contracts/proposals/batch-C-14-to-17.json（域 agent 逐条自证过反证，
#    编排者独立复算 32/32 一致）。新增绑定必须同样附反证并复算，不得手写。 ──
    ('14-roles-permissions-matrix.md', '(\\d+) 项系统操作',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '系统操作行数'),
    ('14-roles-permissions-matrix.md', '(\\d+) 行全否',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|[^|]*\\|(?:\\s*否\\s*\\|){7}', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '主矩阵全否行数'),
    ('14-roles-permissions-matrix.md', '\\| 学习者 \\| 1（人类） \\|[^|]*\\|[^|]*\\| (\\d+) \\|',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){1}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '学习者权限行数'),
    ('14-roles-permissions-matrix.md', '\\| 教练官 \\| 1（常驻，按唤起建会话） \\| 教练官提示词 \\|[^|]*\\| (\\d+) \\|',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){2}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '教练官权限行数'),
    ('14-roles-permissions-matrix.md', '\\| 选材官 \\| 按补切任务临时实例化 \\| 选材官提示词 \\|[^|]*\\| (\\d+) \\|',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){3}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '选材官权限行数'),
    ('14-roles-permissions-matrix.md', '\\| 陪练官 \\| 按补切任务临时实例化 \\| 陪练官提示词 \\|[^|]*\\| (\\d+) \\|',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){4}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '陪练官权限行数'),
    ('14-roles-permissions-matrix.md', '\\| 判读官 \\| 每轮 fresh 实例（不可复用） \\| 判读官提示词 \\|[^|]*\\| (\\d+) \\|',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){5}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '判读官权限行数'),
    ('14-roles-permissions-matrix.md', '\\| 记忆官 \\| 1（确定性本地代码，无提示词） \\| — \\|[^|]*\\| (\\d+) \\|',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){6}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '记忆官权限行数'),
    ('14-roles-permissions-matrix.md', '派生列「教练官·兼帽」的计数为 \\*\\*(\\d+)\\*\\*',
     "len(re.findall(r'^\\|\\s*\\d\\.\\d+\\s*\\|(?:[^|]*\\|){7}\\s*是\\s*\\|', t.split('## 三、角色权限主矩阵')[1].split('## 四、')[0], re.M))", '兼帽派生列权限数'),
    ('15-requirements-mapping-matrix.md', '(\\d+) 条需求',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}\\s*\\|', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M))", 'RMM 需求条数'),
    ('15-requirements-mapping-matrix.md', '(\\d+) 个 L2',
     "len(set(re.findall(r'L1-\\d+\\s+[^·|\\n]+·\\s*([^|/\\n]+?)\\s*(?=\\s*\\||\\s*/|\\s*$)', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M)))", 'RMM 覆盖的 L2 特性数'),
    ('15-requirements-mapping-matrix.md', '(\\d+) / \\d+ 有流程步骤',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}\\s*\\|(?:[^|]*\\|){4}(?!\\s*❌ 无)[^|]*\\|', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M))", '有流程步骤的需求数'),
    ('15-requirements-mapping-matrix.md', '(\\d+) 条无流程步骤',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}\\s*\\|(?:[^|]*\\|){4}\\s*❌ 无\\s*\\|', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M))", '无流程步骤的需求数'),
    ('15-requirements-mapping-matrix.md', '(\\d+) / \\d+ 有用例承接',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}\\s*\\|(?:[^|]*\\|){7}(?!\\s*(?:❌ 无|—))[^|]*\\|', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M))", '有用例承接的需求数'),
    # ── M11：上面两条曾把分母写死成「/ 84」，需求一增即双双退化为 CNT000
    #    「未核查」——门禁对这两个数字直接失去覆盖。改为分母无关，另加本条
    #    独立守住总数：分母由「N 条需求」这条绑定核对，与分子绑定解耦。 ──
    ('15-requirements-mapping-matrix.md', '声明：(\\d+) 行 = \\d+ 条需求',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}\\s*\\|', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M))",
     '主矩阵 REQ 行数（= 需求总数，上面两条的分母靠它守住）'),
    ('15-requirements-mapping-matrix.md', '(\\d+) 条两者皆无',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}\\s*\\|(?:[^|]*\\|){4}\\s*❌ 无\\s*\\|(?:[^|]*\\|){2}(?:\\s*❌ 无\\s*|\\s*—\\s*)\\|', t.split('## 二、主矩阵')[1].split('## 三、')[0], re.M))", '流程与用例两侧皆无的需求数'),
    ('15-requirements-mapping-matrix.md', '\\*\\*有用例、无流程步骤\\*\\* \\| \\*\\*(\\d+) 条\\*\\*',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}', t.split('### 5.2 需求侧缺口 A')[1].split('### 5.3')[0], re.M))", '§5.2 有用例无流程步骤的需求条数'),
    ('15-requirements-mapping-matrix.md', '单需求支撑的 (\\d+) 个特性',
     "len(re.findall(r'^\\|\\s*L1-\\d\\s*\\|', t.split('### 4.4 单需求支撑的')[1].split('**两条结构性结论**')[0], re.M))", '§4.4 单需求支撑特性数'),
    ('15-requirements-mapping-matrix.md', '无流程支撑明细（(\\d+) 条',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}', t.split('### 5.4 无流程支撑明细')[1].split('### 5.5')[0], re.M))", '§5.4 无流程支撑明细行数'),
    ('15-requirements-mapping-matrix.md', '(\\d+) 个 L1 层对象',
     "len(re.findall(r'^\\|\\s*[^\\s\\-|][^|\\n]*\\|', t.split('### 5.5 流程侧检查')[1].split('**L2 层步骤逐条判定**')[0].split('| 判定 |')[-1], re.M))", '§5.5 L1 层判定行数'),
    ('15-requirements-mapping-matrix.md', '个 L1 层对象 \\+ (\\d+) 个 L2 步骤',
     "len(re.findall(r'^\\|\\s*\\*{0,2}1\\.\\d', t.split('**L2 层步骤逐条判定**')[1].split('### 5.6')[0], re.M))", '§5.5 L2 步骤判定行数'),
    ('15-requirements-mapping-matrix.md', '「有流程、无需求」登记表（(\\d+) 处）',
     "len(re.findall(r'^\\|\\s*\\*\\*G\\d\\*\\*', t.split('**「有流程、无需求」登记表')[1].split('### 5.6')[0], re.M))", '§5.5 有流程无需求登记处数'),
    ('15-requirements-mapping-matrix.md', '部分承载的残差登记（(\\d+) 条',
     "len(re.findall(r'^\\|\\s*REQ-\\d{3}', t.split('### 5.6 部分承载的残差登记')[1].split('### 5.7')[0], re.M))", '§5.6 部分承载残差条数'),
    ('16-process-flow.md', 'L1 端到端 (\\d+) 步',
     "len(re.findall(r'^\\|\\s*1\\.\\d\\s*\\|', t.split('### 2.1 L1 步骤表')[1].split('### 2.2')[0], re.M))", 'L1 步骤表行数'),
    ('16-process-flow.md', '只有 \\*\\*(\\d+) 处交接\\*\\*',
     "len(re.findall(r'^\\|\\s*\\*\\*X\\d\\*\\*', t.split('## 三、跨角色交接泳道契约')[1].split('### 3.1')[0], re.M))", '跨角色交接数'),
    ('16-process-flow.md', 'L2 细化 (\\d+) 处',
     "len(re.findall(r'^### 4\\.\\d L2-[AB]', t, re.M))", 'L2 细化小节数'),
    ('16-process-flow.md', '(\\d+) 个决策点全部引用决策树',
     "len(re.findall(r'^\\|\\s*\\*\\*D\\d\\*\\*', t.split('### 2.2 两个判断')[1].split('## 三、')[0], re.M))", 'L1 决策点数'),
    ('17-use-case.md', '(\\d+) 个用例',
     "len(re.findall(r'^## [一二三四五六七八]、UC-\\d\\d', t, re.M))", '用例条数'),
    ('17-use-case.md', '(\\d+) 条 AC 中',
     "len(re.findall(r'^\\|\\s*\\*\\*AC\\d+\\*\\*', t.split('## 九、AC 覆盖矩阵')[1].split('## 十、')[0], re.M))", '§九 AC 覆盖矩阵行数'),
    ('17-use-case.md', '(\\d+) 条由单个用例直接承载',
     "len(re.findall(r'^\\|\\s*\\*\\*AC\\d+\\*\\*.*\\|\\s*✅', t.split('## 九、AC 覆盖矩阵')[1].split('## 十、')[0], re.M))", '§九 单用例直接承载的 AC 数'),
    ('17-use-case.md', '\\*\\*(\\d+) 条替代路径（AC）',
     "len(re.findall(r'^\\s*-\\s\\*\\*AC\\d+\\*\\*｜', t, re.M))", '替代路径条数'),
    ('17-use-case.md', '\\+ (\\d+) 条异常（EX）\\*\\*',
     "len(re.findall(r'^\\s*-\\s\\*\\*EX\\d+\\*\\*｜', t, re.M))", '异常路径条数'),
    ('17-use-case.md', '(\\d+) 条以「转决策树 §X」收口',
     "len(re.findall(r'^\\s*-\\s\\*\\*(?:AC|EX)\\d+\\*\\*｜[^\\n]*决策树', t, re.M))", '转决策树收口的分支数'),
# ── 来自 proposals/batch-A-04-to-07.json（A 组 6 条，B5 拆为 min/max 后 7 条）
#    与 batch-B-10-to-12.json（B 组 25 条），另加本轮 3 条新绑定，合计 36 条。
#    编排者逐条独立复算，方式为三方一致：声明=实测 / 改声明可测 / 删正文任一行可测。
#    B5「均为 2 值」原提案用 max，实测漏报（某条件掉到 1 值仍判过），
#    已按「全等」真义拆为 min/max 两条。04 两条为本轮修正文档后新增。 ──
    ('04-state-table.md', '状态表——(\\d+) 个对象',
     "t.count('| 初 ＼ 标 |')", '状态表张数（front-matter 标题「8 个对象的生命周期穷举」）'),
    ('04-state-table.md', '筛出 (\\d+) 个入选建表',
     "len(re.findall(r'^\\| [^\\-|][^|]*\\|', t.split('| 入选 |')[1].split('**排除')[0], re.M))", '入选建表数（§零 E1 入选表行数）'),
    ('04-state-table.md', '复活路径清单（(\\d+) 条）',
     "len(re.findall(r'^\\| [①②③④⑤⑥] \\|', t, re.M))", '复活路径条数（§九 清单行数）'),
    ('06-decision-table.md', '简化后 8 列 → (\\d+) 条规则',
     "len(re.findall(r'^\\| R\\d+ \\|[^|]*\\|[^|]*\\|[^|]*\\| (?!\\s*X\\s*\\|)', t.split('## 一、DT-1')[1].split('## 二、')[0], re.M))", 'DT-1 简化后实质规则数'),
    ('06-decision-table.md', '均为 (\\d+) 值',
     "min([len(re.findall(r'·', l)) for l in t.split('## 一、DT-1')[1].split('**简化前完整表**')[0].splitlines() if l.startswith('| C')]) + 1", 'DT-1 三条件选择数下界（min 端：某条件掉档即 FAIL）'),
    ('06-decision-table.md', '均为 (\\d+) 值',
     "max([len(re.findall(r'·', l)) for l in t.split('## 一、DT-1')[1].split('**简化前完整表**')[0].splitlines() if l.startswith('| C')]) + 1", 'DT-1 三条件选择数上界（max 端：某条件加档即 FAIL）'),
    ('07-decision-tree.md', '其余 (\\d+) 个判断全在系统内自动完成',
     "len(re.findall(r'◇[^\\n]*？', t.split('## 三、')[1].split('## 四、')[0]))", '§三 队列取用树内的系统内判断数'),
    ('10-data-flow-diagram.md', '逐条登记 (\\d+) 条数据流',
     "len(re.findall(r'^\\|\\s*F\\d+\\s*\\|', t, re.M))", '数据流条数'),
    ('10-data-flow-diagram.md', 'L1 取 (\\d+) 个流程',
     "len(re.findall(r'^\\|\\s*\\*\\*P\\d+\\*\\*\\s*\\|', t.split('## 二、确定流程')[1].split('## 三、')[0], re.M))", 'L1 流程数'),
    ('10-data-flow-diagram.md', '本图的 (\\d+) 个存储区',
     "len(re.findall(r'^\\|\\s*\\*\\*D\\d+\\*\\*\\s*\\|', t.split('## 一、确定业务数据对象')[1].split('## 二、')[0], re.M))", '数据存储区数'),
    ('10-data-flow-diagram.md', '(\\d+) 个外部实体，全部来自',
     "len(re.findall(r'^\\|\\s*\\*\\*E\\d+\\*\\*\\s*\\|', t.split('## 三、确定外部实体')[1].split('## 四、')[0], re.M))", '外部实体数'),
    ('10-data-flow-diagram.md', '网络流只有 (\\d+) 条',
     "len(re.findall(r'^\\|\\s*F\\d+\\s*\\|[^|]*\\|[^|]*\\|[^|]*\\|\\s*网络\\s*\\|', t, re.M))", '网络载体流条数'),
    ('10-data-flow-diagram.md', '其余 (\\d+) 条流仍构成完整闭环',
     "len(re.findall(r'^\\|\\s*F\\d+\\s*\\|[^|]*\\|[^|]*\\|[^|]*\\|(?!\\s*网络\\s*\\|)[^|]*\\|', t, re.M))", '非网络流条数'),
    ('11-system-flow.md', '§9\\.1，(\\d+) 条',
     "len(re.findall(r'^\\|\\s*1\\.[0-9]', t.split('### 9.1')[1].split('### 9.2')[0], re.M))", '§9.1 L1 补偿条目数'),
    ('11-system-flow.md', '§9\\.1 L1 九步 (\\d+) 条',
     "len(re.findall(r'^\\|\\s*1\\.[0-9]', t.split('### 9.1')[1].split('### 9.2')[0], re.M))", '§9.1 声明处（§十② / §九自检）L1 条数'),
    ('11-system-flow.md', 'L2 细分步覆盖 (\\d+) 条',
     "len(re.findall(r'^\\|\\s*1\\.[0-9]', t.split('### 9.2')[1].split('## 十、')[0], re.M))", '§9.2 L2 补偿条目数'),
    ('11-system-flow.md', 'L1 端到端 (\\d+) 步',
     "len(re.findall(r'^│  1\\.\\d ', t.split('## 二、L1 系统流程')[1].split('## 三、')[0], re.M))", 'L1 端到端步数'),
    ('11-system-flow.md', 'L1 步骤数 (\\d+) ≤ 20',
     "len(re.findall(r'^│  1\\.\\d ', t.split('## 二、L1 系统流程')[1].split('## 三、')[0], re.M))", 'L1 步骤数（卡内 ≤20 上限自检）'),
    ('11-system-flow.md', '泳道全部为系统（(\\d+) 条',
     "len(re.findall(r'^\\| [^|]+ \\| (?:L[0-9]|组)', t.split('### 0.3 泳道来源')[1].split('**11 条泳道')[0], re.M))", '泳道数'),
    ('11-system-flow.md', '最长 L2 为 §六 补切链 (\\d+) 步',
     "len(re.findall(r'^1\\.8\\.\\d', t.split('## 六、L2 · 1.8')[1].split('**补偿策略')[0], re.M))", '§六 补切链步数'),
    ('12-user-interface-flow.md', '规范屏幕清单（(\\d+) 个）',
     "len(re.findall(r'^\\|\\s*S\\d+\\s*\\|', t.split('## 二、规范屏幕清单')[1].split('## 三、')[0], re.M))", '规范屏幕数（§二）'),
    ('12-user-interface-flow.md', '(\\d+) 个规范屏幕，按死法 A8',
     "len(re.findall(r'^\\|\\s*S\\d+\\s*\\|', t.split('## 二、规范屏幕清单')[1].split('## 三、')[0], re.M))", '规范屏幕数（frontmatter）'),
    ('12-user-interface-flow.md', '全表 (\\d+) 条边中有',
     "len(re.findall(r'^\\|\\s*[ABCD]\\d+\\s*\\|', t.split('## 三、子图 A')[1].split('### 7.1')[0], re.M))", '箭头台账总边数'),
    ('12-user-interface-flow.md', '有 \\*\\*(\\d+) 条的源不是屏幕\\*\\*',
     "len(re.findall(r'^\\|\\s*[ABCD]\\d+\\s*\\|\\s*(?:◇|唤起入口)', t.split('## 三、子图 A')[1].split('### 7.1')[0], re.M))", '非屏幕源边数'),
    ('12-user-interface-flow.md', '去重后全模型共 (\\d+) 个屏幕框',
     "len(set(re.findall(r'│\\s*(?:▲\\s*)?(I(?:[1-9]|10)|M[1-8])\\s', t.split('## 三、子图 A')[1].split('### 7.1')[0])))", '全模型屏幕框数（frontmatter）'),
    ('12-user-interface-flow.md', 'iOS 侧 (\\d+) 框',
     "len(set(re.findall(r'│\\s*(?:▲\\s*)?(I(?:[1-9]|10))\\s', t.split('## 三、子图 A')[1].split('### 7.1')[0])))", 'iOS 侧框数'),
    ('12-user-interface-flow.md', 'macOS 侧 (\\d+) 框',
     "len(set(re.findall(r'│\\s*(?:▲\\s*)?(M[1-8])\\s', t.split('## 三、子图 A')[1].split('### 7.1')[0])))", 'macOS 侧框数'),
    ('12-user-interface-flow.md', '(\\d+) 张子图，框数 \\*\\*6 / 7 / 4 / 7\\*\\*',
     "len(re.findall(r'^## [三四五六]、子图 [A-D]', t, re.M))", '子图张数'),
    ('12-user-interface-flow.md', '(\\d+) 张子图，框数 6/7/4/7',
     "len(re.findall(r'^## [三四五六]、子图 [A-D]', t, re.M))", '子图张数（§9.4 契约验收项）'),
    ('12-user-interface-flow.md', '仍有 (\\d+) 处缺口',
     "len(re.findall(r'^\\|\\s*G[1-4]\\s*\\|', t.split('**4 处缺口')[1].split('**其余无出处的')[0], re.M))", '§7.4 缺口数 G1–G4'),
    ('12-user-interface-flow.md', '只共享 (\\d+) 个规范屏幕名',
     "len(re.findall(r'^\\|\\s*S(?:2|3|4|11)\\s*\\|', t.split('## 二、规范屏幕清单')[1].split('## 三、')[0], re.M))", '两设备共享的规范屏幕名数'),
    ('12-user-interface-flow.md', '偏离范围仅限 (\\d+) 个规范屏幕',
     "len(re.findall(r'^\\|\\s*S(?:2|3|4|11)\\s*\\|', t.split('## 二、规范屏幕清单')[1].split('## 三、')[0], re.M))", '偏离范围屏幕数（§7.3 B段自查）'),
    ('04-state-table.md', '排除 (\\d+) 个对象',
     "sum(len(c.split('/')) for c in [l.split('|')[1] for l in t.split('| 排除对象 | 理由 |')[1].split('**建模口径偏离')[0].splitlines() if l.startswith('| ') and '---' not in l])", '§零 排除表实枚举对象数（含「/」并列展开，术语/语块为本轮补入）'),
    ('04-state-table.md', '全表共 \\*\\*(\\d+)\\*\\* 个「无」格',
     "len(re.findall(r'(?<=\\| )无(?= \\||$)', t))", '全表「无」格数（零宽口径；str.count 会因相邻格共用竖线漏计 20 处）'),
# ── L2 四轮抓出的 G3：min/max 只取极值，从不数条件行数。删掉 C2 行或把它改名，
#    剩下两行仍是 2 值，min=max=2，「3 个条件均为 2 值」已假而门禁全绿。
#    本条数条件行数，把「有几个条件」也纳入契约；为此把文档里的中文「三个」
#    改成阿拉伯「3 个」——中文数字无法被 claim_regex 捕获，声明形同虚设。 ──
    ('06-decision-table.md', r'\*\*(\d+) 个\*\*条件均为',
     "len([len(re.findall(r'·', l)) for l in t.split('## 一、DT-1')[1].split('**简化前完整表**')[0].splitlines() if l.startswith('| C')])", 'DT-1 条件行数（堵住删行/改名两种逃逸）'),]


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
    """在受限命名空间里求值提取器表达式。

    ⚠️ 必须把命名空间作为 **globals** 传入，不能拆成 (globals, locals)：
    Python 3.9 下列表推导式的**条件与体内**按 global 解析，若 `re`/`len`/`t`
    只在 locals 里，推导式会 NameError → CNT007 永久 FAIL。
    域 agent 因踩到这一点，把 32 条提取器全部写成 comprehension-free 形式；
    修正后推导式可用，但保留防御性断言。
    """
    if "import" in expr or "__" in expr:
        raise ValueError(f"提取器表达式含不允许的构造：{expr[:40]}")
    ns = {**_SAFE_EVAL, "t": text, "__builtins__": {}}
    return eval(expr, ns)  # noqa: S307 — 单一 globals，推导式条件可见


def check_targeted_declarations() -> None:
    checked = 0
    for fname, pat, expr, label in TARGETED:
        p = REQ_DIR / fname
        if not p.exists():
            # 前置条件缺失用 CNT0xx 族，与「声明与实测不符」的 CNT006 区分开——
            # 否则绑定表自检按 CNT006 判定活性时，会被这条前置告警冒充成「活的」
            # 文件不存在 = 本次无法核查，走 UNCHECKED 而非 warn。
            # 同 L2 抓到的免罪符：告警不改变退出码，文档整份被删也能「全绿」。
            unchecked(fname, "CNT000", "文件不存在，定点声明绑定无法执行")
            continue
        text = p.read_text(encoding="utf-8")
        m = re.search(pat, text)
        if not m:
            unchecked(fname, "CNT000", f"未找到「{label}」的声明，本次未做核查")
            continue
        try:
            actual_n = _run_extractor(expr, text)
        except Exception as e:  # 提取器自身坏了——必须报，不能静默跳过
            fail(fname, "CNT007", f"提取器执行失败：{type(e).__name__}（{expr[:40]}）")
            continue
        declared_n = int(m.group(1))
        if declared_n > 0 and actual_n == 0:
            # 这里**必须**判 FAIL，不能降级为告警。曾经的 CNT008 理由是
            # 「锚点失效比内容清零更常见」——但两者在代码看来签名完全相同
            # （declared>0, actual=0），无法区分，于是这条规则变成了免罪符：
            # 摧毁得越彻底，越确定触发告警而不是失败。L2 四轮实测复现：把 10 的
            # 50 条数据流全部改名后，正文实存归零，门禁仍打印「✅ 全绿」exit 0。
            # 真正的「锚点失效」另有通道：声明本身抓不到时走 CNT000/UNCHECKED。
            fail(fname, "CNT008",
                 f"「{label}」声明 {declared_n} 但正文实测 0——内容被清空，或提取器的"
                 f"小节锚点已失效（两者签名相同，不可区分，一律按失败处理）")
            continue
        if declared_n != actual_n:
            fail(fname, "CNT006", f"声明 {label} {declared_n}，正文实测 {actual_n}")
        else:
            checked += 1
    if checked:
        ok(f"定点声明绑定：{checked}/{len(TARGETED)} 条声明与正文实测一致")


# ── 主流程 ────────────────────────────────────────────────────────────
def _strict_requested(argv: list[str]) -> bool:
    """--strict 的解析单独成函数，才能被单元断言直接测。
    此前它内联在 main() 里，自审只能靠整跑 main() 来间接验证——而整跑
    main() 的退出码会被沙箱里其它无关失败撑成 1，变异测试实测该变异逃逸。"""
    return "--strict" in argv


def _extractor_moves(expr: str, text: str) -> bool:
    """删掉正文任意一行后，提取器的实测值是否变化——即它是否对**正文**敏感。

    这是与「改声明数字」互补的活性维度：后者证明比较器是活的，前者才证明
    提取器不是常量。L2 四轮据此注入 "50"/"7"/"9" 三条常量提取器，
    旧的自审报「72/72 全部活的」。
    """
    try:
        base = _run_extractor(expr, text)
    except Exception:
        return False
    lines = text.splitlines(True)
    for i in range(len(lines)):
        try:
            if _run_extractor(expr, "".join(lines[:i] + lines[i + 1:])) != base:
                return True
        except Exception:
            pass
    return False


def check_worktree_clean() -> None:
    """门禁跑的是工作区，不是提交——两者不一致时结论不可迁移。

    L2 四轮抓到的方法论缺陷：编排者对着**脏工作区**跑门禁并汇报「三道门全绿」，
    但提交 `89c45d3` 在干净克隆上其实是**红的**——README.md 的改动只存在于
    工作区，台账 R5-1 却已声称它被修好。本项把「你验证的对象 ≠ 你交付的对象」
    变成机器可判的事：清单覆盖的文件若在 git 里是脏的，本轮结论**只能背书工作区，
    不能背书 HEAD**。

    不直接 fail：并发会话在同一仓库工作时工作区本来就常脏，那是协作常态而非错误。
    但必须进 UNCHECKED——门禁对未提交状态无法背书，这一点不能让「全绿」横幅盖过去。
    """
    import subprocess  # 局部导入：非 git 环境下本项降级为跳过，不影响其余检查
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--",
             "docs/requirements", "docs/swarm/contracts", "README.md"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=20,
        )
    except Exception as e:
        unchecked("tools/verify_docs.py", "MAN004",
                  f"无法读取 git 状态（{type(e).__name__}），本轮结论无法迁移到提交")
        return
    if out.returncode != 0:
        unchecked("tools/verify_docs.py", "MAN004",
                  f"git status 失败（rc={out.returncode}），本轮结论无法迁移到提交")
        return
    dirty = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if dirty:
        unchecked("tools/verify_docs.py", "MAN004",
                  f"清单范围内有 {len(dirty)} 处未提交改动"
                  f"（首条：{dirty[0][:60]}）——本轮全绿只对工作区成立，"
                  f"不能据此声称 HEAD 已通过")


def main() -> int:
    if not REQ_DIR.exists():
        print(f"找不到 {REQ_DIR}")
        return 1

    # --strict 曾经只活在 docstring 里：AGENTS.md 与本文件开头都承诺
    # 「警告也视为失败」，实测两种模式输出逐字节相同、退出码无差别。
    # 承诺存在而实现不存在，比没有承诺更糟——它让人以为告警已被拦。
    strict = _strict_requested(sys.argv[1:])

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
    check_worktree_clean()

    print(f"PASS {len(OK)}")
    for m in OK:
        print(f"  ✓ {m}")

    if WARN:
        print(f"\nWARN {len(WARN)}")
        for m in WARN:
            print(f"  ! {m}")

    if UNCHECKED:
        print(f"\n未核查 {len(UNCHECKED)}（以下检查本次没有执行，"
              f"门禁对它们无法背书，按未通过处理）")
        for m in UNCHECKED:
            print(f"  ? {m}")

    return _verdict(strict)


def _verdict(strict: bool = False) -> int:
    """退出码的唯一判据。抽成函数是为了让它可被单元断言直接测——
    此前它内联在 main() 末尾，自审只能靠搭沙箱端到端地试，而沙箱在变异沙箱
    里没有 git、又带着在飞改动，两头都不成立（实测：5 处变异全被同一次崩溃
    冒充成「已捕获」，信号为零）。"""
    if FAIL or UNCHECKED:
        if FAIL:
            print(f"\nFAIL {len(FAIL)}")
            for m in FAIL:
                print(f"  ✗ {m}")
        return 1

    if strict and WARN:
        print(f"\n--strict：{len(WARN)} 条告警按失败处理")
        for m in WARN:
            print(f"  ! {m}")
        return 1

    print("\n✅ 全绿" + (f"（{len(WARN)} 条告警；--strict 下将判失败）" if WARN else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
