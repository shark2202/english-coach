# Lynx(Vue) 壳层 POC——实测记录

> 采样时间：2026-10-14 · 采样机器：macOS(Apple Silicon) · Node v24.21.0 / npm 11.19.0
> 目的：补上 [tech-eval-lynx-20261014.md](../../docs/tech-eval-lynx-20261014.md) 自陈的「**未实测**」缺口，
> 并针对本次裁决理由（快速预览 / 调试 → 快正向反馈）做定点测量。
> 结论与建议见 [tech-recheck-lynx-20261014.md](../../docs/tech-recheck-lynx-20261014.md)。

## 一、工具链现状（npm 实采）

| 包 | 版本 | 最后更新 | 备注 |
|---|---|---|---|
| `create-vue-lynx` | 0.1.3 | 2026-05-10 | 脚手架；版本序列 0.0.0 → 0.1.3，含 `pre-alpha` 阶段 |
| `vue-lynx` | **0.5.1** | 2026-07-17 | npm 最新；模板锁定 `0.4.0` |
| `@lynx-js/rspeedy` | 0.13.6（实解） | — | Rsbuild 1.7.3 / Rspack 1.7.12 |

- `@lynx-js/vue`、`@lynx-js/cli` 在 npm 上 **不存在（404）**——运行时不在官方 scope 下发布，需经脚手架模板引入。
- 模板依赖固定为 `vue-lynx@0.4.0`，落后于 npm 最新 `0.5.1` 一个次版本。

## 二、开箱成本

| 指标 | 实测 |
|---|---|
| `npm install`（冷） | **41 s**，438 包 |
| `npm install`（热） | 3 s |
| 安全告警 | 9 vulnerabilities（2 low / 4 moderate / 3 high） |
| `npm run dev` 首次出包 | lynx 1.05 s / web 1.09 s |
| `npm run build` | **0.57 s**，双产物 |

Dev server 同时产出三个 URL：

```
➜  Lynx      http://<lan>:3000/main.lynx.bundle          # Lynx Explorer 原生预览用
➜  Web       http://<lan>:3000/main.web.bundle            # 原始 web 产物
➜  Preview   http://<lan>:3000/__web_preview?casename=main.web.bundle   # 浏览器预览
```

产物体积：`main.lynx.bundle` 84.8 kB · `main.web.bundle` 83.2 kB（**一套源码双产物成立**）。

## 三、迭代回路（本次裁决理由的正面实测）

### 3.1 JS / 模板改动 → 热更新 ✅

改 `src/App.vue` 文案 → 日志 `ready built in 0.15 s` → **页面未刷新即更新**
（a11y 快照节点 uid 由 `1_3` 变为 `2_0`，文本已变）。

### 3.2 纯 CSS 改动 → **不热更新，需手动刷新** ⚠️

改 `src/App.css` 背景色 → 日志 `ready built in 0.12 s`（构建确实完成了）→ **页面颜色不变**，
手动刷新后立即生效。

两次独立测试均为同一结果。证据图：

- `css-hot-update-NOT-applied.png` —— CSS 已改、已重建、页面仍是旧样式（退化无样式）
- `render-after-reload.png` —— 刷新后样式全量生效

> **方法论告警（复用时必读）**：Web Preview 把内容渲染进 shadow DOM 的自定义元素
> （`LYNX-VIEW` / `X-VIEW` / `X-TEXT`）。用 `document.querySelectorAll('*')` 探测只能看到
> **11 个节点**，完全看不到 App——据此得出的「CSS 没生效」结论是**假的**。
> 正确探针须穿透 shadow root（本记录实测元素数 **83**），或直接用 a11y 快照。

### 3.3 Agent 可验证性 ✅

预览页可被程序无头验证，三种手段均实测通过：

1. **a11y 快照**——直接得到结构化文本（适合断言文案/结构）
2. **截图**——适合人工与视觉复核
3. **计算样式探针**——穿透 shadow root 后可断言具体 CSS 值

对本仓（agent 蜂群构建）而言，这是 Lynx 相对 Flutter 的一项实打实优势：
浏览器预览天然可被 agent 驱动验证，无需模拟器。

## 四、渲染保真（以本产品真实 UI 约束为样本）

样本 = [app-design §五](../../docs/app-design.md) 的 macOS 三栏 + 衬线阅读区、iOS 单列会话流 + 底部唤起条。

| 能力 | 结果 |
|---|---|
| 三栏 flex 布局（`flex:1` + 定宽侧栏） | ✅ |
| 衬线字体族（Iowan Old Style / Palatino / Georgia） | ✅ |
| **行宽约束** `max-width: 34em` | ✅ 换行点正确 |
| `line-height: 28px` / `letter-spacing` | ✅ |
| 嵌套 `<text>` 行内差异化标注（词汇斜体+配色） | ✅ |
| `v-if` 视图切换 + `@tap` 事件 | ✅ |
| `border-radius` / 配色 / 嵌套 flex | ✅ |

对照截图 `render-after-reload.png`。

## 五、外部事实核验（官方来源）

| # | 来源 | 要点 |
|---|---|---|
| E1 | Lynx 3.7 发布公告（2026-04-16） | 桌面升一级平台；**CSS 覆盖 97%（311/319 属性）**；**元素属性覆盖 73%（179/246）**；桌面支持 mouse / **keyboard（示例明确用 `onKeyDown` 读 `e.key`）** / wheel 事件；发布 6 个 Agent Skills + Lynx DevTool MCP，「让 coding agent 检查运行中页面、验证交互、调试自己的改动」 |
| E2 | Lynxtron 公告 + npm `@lynx-js/lynxtron` | 真实存在且在迭代：**0.0.28**，创建 3 个月，周下载 ~955，3 名维护者，122 issues+PR；Node 宿主进程 + `LynxWindow` + Node-API 原生模块 + contextBridge + fuses |
| E3 | Lynx 2026 路线图 | 2026 年中起改**月度发版**（3.8 五月 / 3.9 六月…），路线图排到 4.5 / 2026-12；明确投入「AI-ready 文档、Agent Skills、工具链」 |
| E4 | Vue Lynx 兼容性文档 | 构建于 `@vue/runtime-core`，响应式 100% 复用；**不支持**：`<TransitionGroup>` FLIP（后台线程无 `getBoundingClientRect`）、`withKeys` 修饰符（**iOS/Android 原生 `event.key` 恒为空**，Web 预览正常） |
| E5 | lynx-ui 发布公告（2026-05-22） | 官方组件集，**仅 iOS / Android / HarmonyOS，不含桌面** |
| E6 | Sparkling | 应用脚手架，**实验性，仅 iOS + Android**（无桌面） |

### 由 E1/E4 得出的重要纠正

`event.key` 恒为空是 **iOS/Android 原生**限制；**桌面端键盘事件完整可用**（E1 明确示例）。
本项目 macOS 是「键盘优先：造句 / 改写 / 复述主战场」——**该风险不成立**。
（原 tech-eval 与 app-design 均未记录此澄清。）

## 六、未实测项（残余不确定性，不得当已验证）

| 项 | 状态 | 影响 |
|---|---|---|
| **Lynx Explorer 原生预览的热更新回路** | ❌ 未测（需 iOS 模拟器/真机） | Phase 1 主战场的真实开发体验仍未知 |
| **Web 预览 ↔ 原生渲染保真差** | ❌ 未测 | 浏览器好看 ≠ iPhone 好看；阅读排版对此敏感 |
| **Lynxtron 实际运行** | ❌ 未测 | macOS 壳可行性只到文档级证据 |
| **L4 原生宿主工作量** | ❌ 未测 | 后台音频/锁屏控制、Handoff、Widget、全局热键的实际自写量 |
| Android / Windows | ❌ 未测 | Phase 2 |

---

**证据文件**：`css-hot-update-NOT-applied.png`、`render-after-reload.png`
**可复现工程**：`poc/shell/`（见 [poc/README.md](../README.md)）