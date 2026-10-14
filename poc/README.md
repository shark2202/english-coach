# POC——Lynx(Vue) 壳层回路探针

为 [Lynx 选型复核](../docs/tech-recheck-lynx-20261014.md) 提供的**可复现**最小工程。
用途只有一个：让「快速预览 / 调试」这条裁决理由随时可被重新测量，而不是停留在口头主张。

## 跑起来

```bash
cd poc/shell
npm install
npm run dev
```

然后打开 dev server 打印的 **Preview** URL（`/__web_preview?casename=main.web.bundle`）。

三条回路可现场复验：

1. **JS/模板热更新** —— 改 `src/App.vue` 里的文案，页面**不刷新**即更新（约 0.15 s）
2. **纯 CSS 不热更新** —— 改 `src/App.css` 的颜色，构建完成（约 0.12 s）但**页面不变**，需手动刷新
3. **Agent 无头验证** —— 该预览页可被 a11y 快照 / 截图 / 计算样式探针直接读取

生产构建：`npm run build` → `dist/main.lynx.bundle` + `dist/main.web.bundle`（一套源码双产物）。

## 这个页面在测什么

`src/App.vue` 不是玩具，它是本产品真实 UI 约束的缩影（对应 [app-design §五](../docs/app-design.md)）：

- **macOS 三栏**——左语境域 / 中阅读区 / 右账本
- **衬线阅读区**——长文专业英语段落（哲学语域），带 `max-width: 34em` 行宽约束
- **行内词汇标注**——英汉不等价的结构呈现（嵌套 `<text>` 差异化样式）
- **iOS 单列会话流** + 底部唤起条（继续 / 2 / 5 / 15 / 只要听）

因为本产品本体是**长文阅读**而非信息流，渲染保真（衬线、换行点、行宽）是选型的真实门槛，
而不是随手摆几个方块就能证明的事。

## 测量结果

见 [evidence/measurements.md](evidence/measurements.md)（含截图证据与未测项清单）。

## 复验时注意

Web Preview 把内容渲染进 **shadow DOM 自定义元素**（`LYNX-VIEW` / `X-VIEW` / `X-TEXT`）。
用 `document.querySelectorAll('*')` 探测只能看到 11 个节点、**看不到 App 本身**，
据此判断「样式没生效」会得出假结论。探针须穿透 shadow root（实测元素数 83），或直接读 a11y 快照。