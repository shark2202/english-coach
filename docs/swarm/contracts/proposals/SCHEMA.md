# CNT006 定点声明绑定 · 提案 schema

`tools/verify_docs.py` 的 `check_targeted_declarations()` 按下表逐条核对：
文件里若能用 `claim_regex` 抓到含一个数字的声明，就用 `extractor` 数出正文实测值，
不一致即 `[CNT006]` FAIL。**找不到声明 → `[CNT000]` 告警，绝不静默通过。**

- `claim_regex`：Python 正则，须含**恰好一个**捕获组，组 1 是被声明的数字。
- `extractor`：**Python 表达式**，只允许用到变量 `t`（该文件全文 `str`）与 `re`。
  例：`len(set(re.findall(r"ELMT_\d{4}", t)))`
- 提案须**自带反证**：把声明改成错误数字后，`extractor` 必须能测出不一致。
  没有反证的提案不予采纳——这是三轮 L2 用变异测试证伪自审套件后确立的准入条件。
