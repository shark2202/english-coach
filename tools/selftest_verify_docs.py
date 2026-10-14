#!/usr/bin/env python3
"""L1 校验器自审（契约修订 R5）。

动机：校验器是门禁，门禁自身的失灵不会被任何检查发现。首轮已实际发生两次：
  · frontmatter 的 batch 值带引号 → OWN001 把 16 份合规文档全判成越权写入；
  · 本文件编写时又测出 ST002 曾误报。
两次都是「校验器报错而非漏报」——看似安全，实际是把门禁变成噪声，
真越权到来时会被整体忽略（告警疲劳）。

因此门禁必须有负向测试：每条检查都要证明它在坏输入上真的会 FAIL。
只跑一遍真实文档是不够的——真实文档当前全合规，绿灯证明不了任何事。

用法：
    python3 tools/selftest_verify_docs.py
退出码：0 = 门禁可信；1 = 有检查形同虚设
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("vd", ROOT / "tools" / "verify_docs.py")
vd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vd)

TMP = Path(tempfile.mkdtemp(prefix="vd-selftest-"))
PASSED: list[str] = []
BROKEN: list[str] = []


def codes(new_fails: list[str]) -> list[str]:
    return [m.split("]", 1)[0].lstrip("[") for m in new_fails]


def _guard(name: str, fn) -> str | None:
    """执行一个用例体并捕获异常。

    ⚠️ 变异测试逼出这个函数：某个检查抛异常会让整轮 selftest 中断，
    **连「门禁失灵」报告都出不来**——崩溃既不能冒充捕获，也不该让 harness 失声。
    这里把异常记成显式失败，于是「检查自身被变异搞崩」会立刻显示为一条失灵项。
    """
    try:
        fn()
        return None
    except Exception as e:  # noqa: BLE001 — harness 必须吞掉一切
        return f"{type(e).__name__}: {e}"


def expect_fail(name: str, code: str, fn) -> None:
    f0, w0 = len(vd.FAIL), len(vd.WARN)
    crashed = _guard(name, fn)
    if crashed:
        BROKEN.append(f"{name} → 期望拦截 {code}，但检查抛异常（{crashed[:70]}）")
        return
    got = codes(vd.FAIL[f0:])
    if code in got:
        PASSED.append(f"{name} → 正确拦截 {code}")
    else:
        BROKEN.append(f"{name} → 期望拦截 {code}，实际 {'/'.join(got) or '放行'}")


def expect_warn(name: str, code: str, fn) -> None:
    """前置条件缺失类判定走 warn() 而非 fail()——它们报告「兜底失效」，
    不是「产物有错」。误报它们等于把兜底告警降级成噪声。"""
    f0, w0 = len(vd.FAIL), len(vd.WARN)
    crashed = _guard(name, fn)
    if crashed:
        BROKEN.append(f"{name} → 期望告警 {code}，但检查抛异常（{crashed[:70]}）")
        return
    got = [m.split("]", 1)[0].lstrip("[") for m in vd.WARN[w0:]]
    if code in got:
        PASSED.append(f"{name} → 正确告警 {code}")
    else:
        BROKEN.append(f"{name} → 期望告警 {code}，实际 {'/'.join(got) or '静默'}")


def expect_pass(name: str, fn) -> None:
    f0, w0 = len(vd.FAIL), len(vd.WARN)
    crashed = _guard(name, fn)
    if crashed:
        BROKEN.append(f"{name} → 正例被检查抛异常（{crashed[:70]}）")
        return
    got = codes(vd.FAIL[f0:])
    if got:
        BROKEN.append(f"{name} → 正例被误报 {','.join(got)}")
    else:
        PASSED.append(f"{name} → 正确放行")


def doc(fname: str, fm: str, body: str = "正文\n") -> Path:
    p = TMP / fname
    p.write_text(f"---\n{fm}\n---\n\n{body}", encoding="utf-8")
    return p


def raw(fname: str, text: str) -> Path:
    p = TMP / fname
    p.write_text(text, encoding="utf-8")
    return p


def main() -> int:  # noqa: C901 — 测试函数，逐条平铺比抽象更易读
    own = vd.load_ownership()
    if not own:
        print("✗ 契约归属加载失败，OWN 测试无从谈起")
        return 1

    # 让自审彻底自足：vd.REQ_DIR 指向按契约造出的夹具目录，而不是仓库真实目录。
    # 否则在变异测试的 /tmp 沙箱里该目录为空，多个用例会**空断言地**通过——
    # 那是虚假安全感的一种典型形态（三轮 L2 指出过同类问题）。
    FIX_REQ = TMP / "contract-req"
    FIX_REQ.mkdir(exist_ok=True)
    for name in own:
        (FIX_REQ / name).write_text(
            "---\ntype: T\ntitle: t\ndescription: d\nstatus: 草稿\n---\n\n夹具\n", encoding="utf-8")
    vd.REQ_DIR = FIX_REQ

    print("— 引号归一化（经 OWN001 端到端触发，不做裸布尔断言） —")
    # 归属随契约变化（修正批次会接管文件），故从契约现读，不写死批次 id
    target_name = "12-user-interface-flow.md"
    right = own[target_name]
    wrong = next(b for b in own.values() if b != right)

    # ⚠️ 本节曾把 `parse_frontmatter(...) == "batch-08-ui-dar"` 这种裸布尔表达式
    # 直接传给 expect_pass——它从不触碰 vd.FAIL，删掉 unquote() 也照样打 ✓
    # （二轮 L2 变异测试证伪）。改为：写一份文件，让 OWN001 真正跑一遍，
    # 只有「解析结果与契约归属一致」时才会放行。删掉 unquote() → OWN001 FAIL → 用例红。
    for variant, label in (('batch: "{}"', "双引号"), ("batch: '{}'", "单引号"), ("batch: {}", "无引号")):
        expect_pass(
            f"{label}写法均被 OWN001 判为归属正确",
            lambda v=variant: vd.check_ownership(doc(target_name, v.format(right)), own),
        )

    print("\n— OWN001/OWN002 写入范围 —")
    expect_fail(
        "冒名顶替他批次",
        "OWN001",
        lambda: vd.check_ownership(doc(target_name, f'batch: "{wrong}"'), own),
    )
    expect_fail(
        "未声明批次",
        "OWN001",
        lambda: vd.check_ownership(doc(target_name, 'status: "已冻结"'), own),
    )
    expect_fail(
        "声明为空",
        "OWN001",
        lambda: vd.check_ownership(doc(target_name, "batch:"), own),
    )
    expect_fail(
        "契约未授权的新文件",
        "OWN002",
        lambda: vd.check_ownership(doc("99-未授权新文件.md", f'batch: "{right}"'), own),
    )
    expect_fail(
        "契约 owns 清单未覆盖此文件 → OWN002（正向断言：覆盖不足必须报）",
        "OWN002",
        lambda: vd.check_contract_covers_all({"03-data-dictionary.md": "batch-x"}),
    )
    expect_pass(
        "契约 owns 清单完整时不得误报",
        lambda: vd.check_contract_covers_all(own),
    )

    print("\n— FM001 frontmatter 必填 —")
    expect_fail("缺 status", "FM001", lambda: vd.check_frontmatter(doc("t.md", 'type: X\ntitle: "y"')))
    expect_pass(
        "四字段齐备",
        lambda: vd.check_frontmatter(doc("t.md", 'type: X\ntitle: "y"\ndescription: "z"\nstatus: 草稿')),
    )

    print("\n— LK001 内部链接 —")
    expect_fail(
        "悬空链接",
        "LK001",
        lambda: vd.check_links(doc("t.md", 'status: "草稿"', body="见 [缺失](./nonexistent-xyz.md)\n")),
    )
    expect_pass(
        "外链与锚点不校验",
        lambda: vd.check_links(doc("t.md", 'status: "草稿"', body="见 [x](https://a.example) 与 [y](#z)\n")),
    )

    print("\n— ST001 陈旧表述 —")
    expect_fail(
        "旧平台路线残留",
        "ST001",
        lambda: vd.check_stale(doc("t.md", 'status: "草稿"', body="五平台路线图\n")),
    )

    print("\n— CNT 声明计数 vs 实测 —")
    expect_fail(
        "BDD 关系数不符",
        "CNT001",
        lambda: vd.check_declared_counts(
            doc("02-x.md", 'description: "21 条关系"', body="| 1.1 | a |\n| 1.2 | b |\n")
        ),
    )
    expect_pass(
        "DD 字段数相符",
        lambda: vd.check_declared_counts(
            doc("03-x.md", 'description: "2 个字段"', body="| DD001 | a | b |\n| DD002 | a | b |\n")
        ),
    )

    print("\n— EMP001 空单元格 —")
    expect_fail(
        "DD 行有空单元",
        "EMP001",
        lambda: vd.check_empty_cells(doc("t.md", 'status: "草稿"', body="| DD001 | a |  |\n")),
    )

    print("\n— HF001 草稿诚实性 —")
    expect_fail(
        "草稿却声称校验通过",
        "HF001",
        lambda: vd.check_draft_honesty(doc("t.md", 'status: "草稿"', body="已完成交叉校验\n")),
    )
    expect_pass(
        "草稿如实写未完成",
        lambda: vd.check_draft_honesty(doc("t.md", 'status: "草稿"', body="尚未校验\n")),
    )

    print("\n— FIX001 跨文档修正闭环 —")
    target = doc("fix-target.md", 'status: "草稿"', body="补充字段 DD801\n")
    ledger = TMP / "ledger.json"
    orig, orig_root = vd.FIX_LEDGER, vd.ROOT
    try:
        vd.FIX_LEDGER = ledger
        vd.ROOT = TMP  # 夹具在临时目录，校验器按 ROOT 解析 target_file
        ledger.write_text(
            json.dumps(
                {
                    "fixes": [
                        {"id": "T1", "target_file": "fix-target.md",
                         "evidence": {"type": "contains", "string": "DD801"}}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        expect_pass("证据成立即放行", vd.check_applied_fixes)
        ledger.write_text(
            json.dumps(
                {
                    "fixes": [
                        {"id": "T1", "target_file": "fix-target.md",
                         "evidence": {"type": "contains", "string": "DD999"}}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        expect_fail("声称已修但证据不存在", "FIX001", vd.check_applied_fixes)
        _write_ledger(ledger, [
            {"id": "T1", "target_file": "fix-target.md", "superseded_by": "T2",
             "evidence": {"type": "contains", "string": "根本不存在的字串"}},
        ])
        expect_pass("已被取代的条目不再参与证据核对", vd.check_applied_fixes)
        ledger.write_text(
            json.dumps(
                {
                    "fixes": [
                        {"id": "T1", "target_file": "fix-target.md",
                         "evidence": {"type": "not_contains", "string": "DD999"}}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        expect_pass("not_contains 证据成立", vd.check_applied_fixes)
        ledger.write_text(
            json.dumps(
                {
                    "fixes": [
                        {"id": "T1", "target_file": "fix-target.md",
                         "evidence": {"type": "not_contains", "string": "DD801"}}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        expect_fail("声称已删但仍存在", "FIX001", vd.check_applied_fixes)
        _write_bad(ledger)
        expect_fail("台账 JSON 非法", "FIX002", vd.check_applied_fixes)
        _write_ledger(ledger, [{"id": "T1", "target_file": "fix-target.md",
                                "evidence": {"type": "随便", "string": "x"}}])
        expect_fail("证据类型未定义", "FIX002", vd.check_applied_fixes)
    finally:
        vd.FIX_LEDGER = orig
        vd.ROOT = orig_root

    print("\n— MAN001 内容指纹（内容级越权） —")
    mtarget = doc("man-target.md", 'status: "草稿"', body="原始内容\n")
    man = TMP / "manifest.json"
    orig_man, orig_ledger, orig_root = vd.MANIFEST, vd.FIX_LEDGER, vd.ROOT
    lock = TMP / "man.lock"
    orig_lock = vd.MANIFEST_LOCK
    try:
        vd.MANIFEST = man
        vd.MANIFEST_LOCK = lock          # 夹具清单必须配一把匹配的锁，否则先在 MAN003 上翻车
        vd.ROOT = TMP
        orig_sha = vd.sha256_of(mtarget)
        man.write_text(json.dumps({
            "files": [{"path": "man-target.md", "sha256": orig_sha}]
        }, ensure_ascii=False), encoding="utf-8")
        lock.write_text(vd.sha256_of(man) + "\n", encoding="utf-8")
        expect_pass("内容未变", vd.check_content_manifest)

        mtarget.write_text("---\nstatus: \"草稿\"\n---\n\n被人悄悄改掉\n", encoding="utf-8")
        expect_fail("内容改了但未申报", "MAN001", vd.check_content_manifest)

        # 洗白路径：同时改夹具内容与清单里的指纹——锁文件必须仍能发现
        man.write_text(json.dumps({
            "files": [{"path": "man-target.md", "sha256": vd.sha256_of(mtarget)}]
        }, ensure_ascii=False), encoding="utf-8")
        expect_fail("改清单洗白 → MAN003 锁失配", "MAN003", vd.check_content_manifest)
        lock.write_text(vd.sha256_of(man) + "\n", encoding="utf-8")

        # 回到「清单与原内容匹配」的状态，再测申报通道
        man.write_text(json.dumps({
            "files": [{"path": "man-target.md", "sha256": orig_sha}]
        }, ensure_ascii=False), encoding="utf-8")
        lock.write_text(vd.sha256_of(man) + "\n", encoding="utf-8")

        vd.FIX_LEDGER = TMP / "declared.json"
        _write_ledger(vd.FIX_LEDGER, [{"id": "D1", "target_file": "man-target.md",
                                       "evidence": {"type": "contains", "string": "悄悄"},
                                       "new_sha256": vd.sha256_of(mtarget)}])
        expect_pass("已申报的新指纹", vd.check_content_manifest)

        _write_ledger(vd.FIX_LEDGER, [{"id": "D1", "target_file": "man-target.md",
                                       "evidence": {"type": "contains", "string": "悄悄"},
                                       "new_sha256": "0" * 64}])
        expect_fail("申报的指纹与实际不符", "MAN001", vd.check_content_manifest)
    finally:
        vd.MANIFEST = orig_man
        vd.FIX_LEDGER = orig_ledger
        vd.MANIFEST_LOCK = orig_lock
        vd.ROOT = orig_root

    print("\n— MAN002 清单 JSON 非法（须先过锁校验才能走到解析） —")
    man_bad = TMP / "man-bad.json"
    bad_lock = TMP / "man-bad.lock"
    orig_man2, orig_lock2 = vd.MANIFEST, vd.MANIFEST_LOCK
    try:
        man_bad.write_text("{ not json", encoding="utf-8")
        bad_lock.write_text(vd.sha256_of(man_bad) + "\n", encoding="utf-8")
        vd.MANIFEST, vd.MANIFEST_LOCK = man_bad, bad_lock
        expect_fail("清单 JSON 非法 → MAN002", "MAN002", vd.check_content_manifest)
    finally:
        vd.MANIFEST, vd.MANIFEST_LOCK = orig_man2, orig_lock2

    print("\n— REF001 DD 引用有效性 —")
    dd_defs = {"DD101", "DD203", "DD410", "DD703"}
    req_tmp = TMP / "req"
    req_tmp.mkdir(exist_ok=True)
    (req_tmp / "good.md").write_text("---\nstatus: \"草稿\"\n---\n\n取值见 DD703 与 DD101–DD410 区间\n", encoding="utf-8")
    orig_req = vd.REQ_DIR
    try:
        vd.REQ_DIR = req_tmp
        expect_pass("引用全部有定义", lambda: vd.check_dd_references(dd_defs))
        (req_tmp / "bad.md").write_text("---\nstatus: \"草稿\"\n---\n\n取值见 DD411 与 DD703\n", encoding="utf-8")
        expect_fail("引用不存在的编号", "REF001", lambda: vd.check_dd_references(dd_defs))
        (req_tmp / "bad.md").unlink()
        # ⚠️ 本用例曾用 `DD9xx` 做数据——`DD\d{3}` 根本匹配不到它，
        # 于是「删掉整条 skip 分支也照样打 ✓」（二轮 L2 变异测试证伪）。
        # 改为真正的对照：同一个悬空编号 DD999，带「待定义」放行、不带就拦。
        todo = req_tmp / "todo.md"
        todo.write_text("---\nstatus: \"草稿\"\n---\n\nDD999 待定义，暂缺\n", encoding="utf-8")
        expect_pass("显式待定义不算悬空", lambda: vd.check_dd_references(dd_defs))
        todo.write_text("---\nstatus: \"草稿\"\n---\n\n取自 DD999 的派生值\n", encoding="utf-8")
        expect_fail("同一个编号去掉「待定义」即须拦截", "REF001", lambda: vd.check_dd_references(dd_defs))
    finally:
        vd.REQ_DIR = orig_req

    print("\n— RM001 README 索引完整性 —")
    # 二轮 L2 指出：RM001 是 AGENTS.md 亲口称「当前最容易踩的一条」，却零测试。
    readme = TMP / "README.md"
    orig_readme = vd.ROOT
    try:
        vd.ROOT = TMP
        readme.write_text("# t\n", encoding="utf-8")          # 索引为空 → 每个文件都未登记
        expect_fail("README 未登记需求文档 → RM001", "RM001", vd.check_readme_index)
        readme.write_text(
            "# t\n" + "".join(f"- [{f.name}](docs/requirements/{f.name})\n"
                              for f in sorted(vd.REQ_DIR.glob("*.md"))),
            encoding="utf-8",
        )
        expect_pass("README 已登记全部需求文档", vd.check_readme_index)
        # 登记不全也必须报：抽掉最后一条
        readme.write_text(
            "# t\n" + "".join(f"- [{f.name}](docs/requirements/{f.name})\n"
                              for f in sorted(vd.REQ_DIR.glob("*.md"))[:-1]),
            encoding="utf-8",
        )
        expect_fail("只差一条也不能放行", "RM001", vd.check_readme_index)
    finally:
        vd.ROOT = orig_readme

    print("\n— CNT002/004/005 二轮补齐的负例 —")
    # 字形数 3（L0 的 └ + 两个 L2 的 ├/└）→ l2_actual = 3 - 1 = 2
    tree = "```\nL0\n├─ a\n│  └─ b\n└─ c\n```\n"
    ftree = doc("01-x.md", 'description: "2 个 L1 / 2 个 L2"',
                body="## 二、\nL1-1 甲\nL1-2 乙\n## 三、\n" + tree)
    expect_pass("特性树 L1/L2 计数相符", lambda: vd.check_declared_counts(ftree))
    expect_fail(
        "L1 数不符",
        "CNT004",
        lambda: vd.check_declared_counts(
            doc("01-x.md", 'description: "5 个 L1 / 2 个 L2"',
                body="## 二、\nL1-1 甲\nL1-2 乙\n## 三、\n" + tree)),
    )
    expect_fail(
        "L2 数不符",
        "CNT005",
        lambda: vd.check_declared_counts(
            doc("01-x.md", 'description: "2 个 L1 / 5 个 L2"',
                body="## 二、\nL1-1 甲\nL1-2 乙\n## 三、\n" + tree)),
    )
    fbdd = doc("02-x.md", 'description: "3 个业务数据对象"',
               body="## 二、BDD-1 · 甲域（语料 / 语块）\n## 三、BDD-2 · 乙域（档案）\n")
    expect_pass("BDD 对象数相符", lambda: vd.check_declared_counts(fbdd))
    expect_fail(
        "BDD 对象数不符",
        "CNT002",
        lambda: vd.check_declared_counts(
            doc("02-x.md", 'description: "9 个业务数据对象"',
                body="## 二、BDD-1 · 甲域（语料 / 语块）\n## 三、BDD-2 · 乙域（档案）\n")),
    )

    print("\n— 前置条件类判定码（三轮 L2 点名的 7 个零覆盖码） —")
    expect_fail("无 frontmatter → FM000", "FM000",
                lambda: vd.check_frontmatter(raw("nofm.md", "正文，无 frontmatter\n")))
    expect_warn("已冻结与待并存 → HF002", "HF002",
                lambda: vd.check_draft_honesty(doc("t.md", 'status: "已冻结，待补"')))
    expect_warn("状态表有矩阵但无事件表 → ST002", "ST002",
                lambda: vd.check_state_table(
                    raw("04-x.md", "| 初 ＼ 标 | A | B |\n|---|---|---|\n| A | — | — |\n")))
    # 以下四个码要求「前置文件缺失/损坏」，均以替换模块级路径的方式触发
    for code, attr, payload, fn in [
        ("OWN000", "CONTRACT", "{ not json", "load_ownership"),
        ("FIX000", "FIX_LEDGER", '{"fixes": []}', "check_applied_fixes"),
        ("MAN000", "MANIFEST", None, "check_content_manifest"),
        ("RM000", "ROOT", None, "check_readme_index"),
    ]:
        holder = TMP / f"missing-{code}"
        holder.parent.mkdir(exist_ok=True)
        if payload is not None:
            holder.write_text(payload, encoding="utf-8")
        saved = getattr(vd, attr)
        try:
            setattr(vd, attr, holder)
            expect_warn(f"前置文件缺失/损坏 → {code}", code, getattr(vd, fn))
        finally:
            setattr(vd, attr, saved)

    print("\n— CNT006 定点声明绑定 —")
    tgt = TMP / "targeted"
    tgt.mkdir(exist_ok=True)
    (tgt / "11-system-flow.md").write_text(
        "以 2 条补偿条目覆盖\n\n### 9.1 L1 九步\n\n"
        "| 步骤 | 失败模式 |\n|---|---|\n| 1.1 a | b |\n| 1.2 c | d |\n", encoding="utf-8")
    (tgt / "13-display-action-response.md").write_text(
        "共 3 张元素表 ELMT_0101 ELMT_0102 ELMT_0103；引用 DD101、DD102、DD103 共 3 个字段号\n",
        encoding="utf-8")
    orig_t = vd.REQ_DIR
    orig_targeted = vd.TARGETED
    try:
        vd.REQ_DIR = tgt
        expect_pass("定点声明与正文一致", vd.check_targeted_declarations)
        (tgt / "11-system-flow.md").write_text(
            "以 9 条补偿条目覆盖\n\n### 9.1 L1 九步\n\n"
            "| 步骤 | 失败模式 |\n|---|---|\n| 1.1 a | b |\n| 1.2 c | d |\n", encoding="utf-8")
        expect_fail("补偿条目数声明不符 → CNT006", "CNT006", vd.check_targeted_declarations)
        (tgt / "11-system-flow.md").write_text(
            "以 2 条补偿条目覆盖\n\n### 9.1 L1 九步\n\n"
            "| 步骤 | 失败模式 |\n|---|---|\n| 1.1 a | b |\n| 1.2 c | d |\n", encoding="utf-8")
        (tgt / "13-display-action-response.md").write_text(
            "共 3 张元素表 ELMT_0101 ELMT_0102 ELMT_0103；引用 DD101–DD103 共 30 个字段号\n",
            encoding="utf-8")
        expect_fail("DD 字段号声明不符 → CNT006（三轮 L2 实测漏过的那类）",
                    "CNT006", vd.check_targeted_declarations)
        (tgt / "13-display-action-response.md").write_text(
            "本文件本轮不声明元素表数\n", encoding="utf-8")
        expect_warn("未找到声明时须告警而非静默通过", "CNT000",
                    vd.check_targeted_declarations)
    finally:
        vd.REQ_DIR = orig_t
        vd.TARGETED = orig_targeted

    # OWN000 的两个分支必须分别测：exists() 分支与 JSON 解析分支。
    # 只测后者的话，把 exists() 判定关掉对结果毫无影响——变异测试实测过这一处逃逸。
    saved_contract = vd.CONTRACT
    try:
        vd.CONTRACT = TMP / "绝对不存在的契约.json"
        expect_warn("契约文件不存在 → OWN000（exists 分支）", "OWN000", vd.load_ownership)
    finally:
        vd.CONTRACT = saved_contract

    # ── 汇总 ──
    print("\n" + "=" * 62)
    for m in PASSED:
        print(f"  ✓ {m}")
    if BROKEN:
        print(f"\n❌ 门禁失灵 {len(BROKEN)} 项")
        for m in BROKEN:
            print(f"  ✗ {m}")
        return 1
    print(f"\n✅ 门禁自审通过：{len(PASSED)} 项检查在坏输入上均会 FAIL")
    return 0


def _write_ledger(ledger: Path, fixes: list[dict]) -> None:
    ledger.write_text(json.dumps({"fixes": fixes}, ensure_ascii=False), encoding="utf-8")


def _write_bad(ledger: Path) -> None:
    ledger.write_text("{ not json", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
