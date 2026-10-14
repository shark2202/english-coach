# english-coach

AI 英语学习教练——碎片时间语感训练。独立项目。

**一句话**：账本优先、App 是壳。学习者随时唤起、随时中断不丢进度；碎片时间按档位练语感（语块 × 语境复现 × 输出判定）；iOS/macOS 先行、五平台路线；纯单机基线 + 可选同步 + 设备间无缝切换。

## 状态

设计阶段（未实现）。设计文档待审阅：

- [docs/kernel.md](docs/kernel.md) —— **最小理论内核**（十条机制 + 术语表，先读这个）
- [docs/org-design.md](docs/org-design.md) —— 教练组织设计（english-coach-bureau 骨架 v0.1，2026-10-13）
- [docs/app-design.md](docs/app-design.md) —— App 设计（跨平台运行时载体 v0.2，2026-10-14：双模运行——纯单机基线 + 可选同步 + 无缝切换）
- [docs/tech-eval-lynx-20261014.md](docs/tech-eval-lynx-20261014.md) —— Lynx（Vue 版）选型评估（2026-10-14）：四端可行但 Linux 断角 + Vue×桌面双早期 + 宿主自建成本，不替代 Flutter 主选，留作跟踪项

## 独立交付

本仓**自带全部理解与实施所需材料，无外部仓库依赖**：

- **阅读顺序**：README → kernel.md（理论内核）→ org-design.md → app-design.md → tech-eval-lynx；
- 设计文档中 "ai-native 仓" 字样仅为**溯源版本锚**，其机制定义已内嵌于 kernel.md，不访问该仓不影响理解与实施；
- **验收标准**：在任意机器 clone 本仓，按上述顺序读完即可开工；后续 Flutter 代码、账本 schema、角色提示词配置全部落在本仓；
- 设计本身保证 App 将来可独立分发：账本为本地文件契约（App 可整体替换）、BYOK（无账号无服务端依赖）、双模运行（纯单机即完整产品）；
- **交付前待裁决**：License（MIT / 专有 / 暂不公开）——对外分发前必须定。

## 技术栈（设计决策）

- Flutter 单代码库：iOS/macOS 先行 → Ubuntu/Windows/Android
- 核心层 `coach_core` 纯 Dart 包（零 UI 依赖，可无头测试）；记忆官调度为确定性本地代码
- 账本 = 本地 md/jsonl 文件契约（平台无关，App 可整体替换）
- AI：BYOK（云 API / 本地 Ollama·MLX），离线判定三级（T0 预嵌 / T1 本地模型 / T2 联网补判）
- 同步：可选叠加层，iCloud 先行，目录即契约、同步工具可换

## 理论出处

组织机制（可恢复性不变量族 I-TREE/I-NOLOSS/I-RESUME/I-REFORM、I-DISC 判别分离、触点极简等）源自 ai-native 理论仓（`/Users/mac/ai-native`）。设计文档内引用的 `specs/`、`proposals/`、`theory/` 路径均指该仓，仅作版本锚引用，文件不在本项目内。

## 计划

- **Phase 1**：iOS + macOS MVP（验收 AC 十一条见 app-design §十）
- **Phase 2**：Android/Windows/Ubuntu 三平台 + CLI 壳（「壳可替换」实测）
- **Phase 3**：打磨（仪表盘/Widget 全量/语境域商店/自带材料导入）
