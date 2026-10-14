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


def expect_fail(name: str, code: str, fn) -> None:
    f0, w0 = len(vd.FAIL), len(vd.WARN)
    fn()
    got = codes(vd.FAIL[f0:])
    if code in got:
        PASSED.append(f"{name} → 正确拦截 {code}")
    else:
        BROKEN.append(f"{name} → 期望拦截 {code}，实际 {'/'.join(got) or '放行'}")


def expect_pass(name: str, fn) -> None:
    f0, w0 = len(vd.FAIL), len(vd.WARN)
    fn()
    got = codes(vd.FAIL[f0:])
    if got:
        BROKEN.append(f"{name} → 正例被误报 {','.join(got)}")
    else:
        PASSED.append(f"{name} → 正确放行")


def doc(fname: str, fm: str, body: str = "正文\n") -> Path:
    p = TMP / fname
    p.write_text(f"---\n{fm}\n---\n\n{body}", encoding="utf-8")
    return p


def main() -> int:  # noqa: C901 — 测试函数，逐条平铺比抽象更易读
    own = vd.load_ownership()
    if not own:
        print("✗ 契约归属加载失败，OWN 测试无从谈起")
        return 1

    print("— 引号归一化 —")
    for variant in ('batch: "batch-08-ui-dar"', "batch: 'batch-08-ui-dar'", "batch: batch-08-ui-dar"):
        expect_pass(
            f"parse_frontmatter 接受写法 {variant.split(':', 1)[1].strip()}",
            lambda v=variant: vd.parse_frontmatter(f"---\n{v}\n---\n").get("batch") == "batch-08-ui-dar",
        )

    print("\n— OWN001/OWN002 写入范围 —")
    # 归属随契约变化（修正批次会接管文件），故从契约现读，不写死批次 id
    target_name = "12-user-interface-flow.md"
    right = own[target_name]
    wrong = next(b for b in own.values() if b != right)
    p = doc(target_name, f'batch: "{right}"')
    expect_pass("归属正确的带引号写法", lambda: vd.check_ownership(p, own))
    expect_pass(
        "归属正确的不带引号写法",
        lambda: vd.check_ownership(doc(target_name, f"batch: {right}"), own),
    )
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
        "空契约不得误判全部越权",
        "OWN002",
        lambda: vd.check_contract_covers_all({"03-data-dictionary.md": "batch-x"}),
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
    try:
        vd.MANIFEST = man
        vd.ROOT = TMP
        man.write_text(json.dumps({
            "files": [{"path": "man-target.md", "sha256": vd.sha256_of(mtarget)}]
        }, ensure_ascii=False), encoding="utf-8")
        expect_pass("内容未变", vd.check_content_manifest)

        mtarget.write_text("---\nstatus: \"草稿\"\n---\n\n被人悄悄改掉\n", encoding="utf-8")
        expect_fail("内容改了但未申报", "MAN001", vd.check_content_manifest)

        # 已申报的新指纹 → 合法
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
        vd.ROOT = orig_root

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
        (req_tmp / "todo.md").write_text("---\nstatus: \"草稿\"\n---\n\nDD9xx 待定义，暂缺\n", encoding="utf-8")
        expect_pass("显式待定义不算悬空", lambda: vd.check_dd_references(dd_defs))
    finally:
        vd.REQ_DIR = orig_req

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
