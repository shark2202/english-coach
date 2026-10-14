<script setup lang="ts">
import { ref } from 'vue-lynx'
import './App.css'

// POC 探针（2026-10-14）：复刻 app-design §五 的三个关键 UI 约束，检验 Lynx(Vue) 能否承载。
// 1) iOS 单列会话流 + 底部唤起条
// 2) macOS 三栏 + 中栏衬线阅读区（行宽约束）——本产品本体是长文专业英语阅读
// 3) 行内词汇标注（英汉不等价的结构呈现）
const activeTab = ref<'ios' | 'mac'>('mac')

const passage =
  'The philosopher who insists that language is a transparent medium of thought ' +
  'has already conceded too much to the metaphor of the window. Language is not a ' +
  'window; it is the instrument by which thought is performed, and every ' +
  'instrument shapes what can be done with it.'
</script>

<template>
  <view class="Root">
    <view class="TabBar">
      <text :class="activeTab === 'mac' ? 'Tab Tab--on' : 'Tab'" @tap="activeTab = 'mac'">macOS 三栏</text>
      <text :class="activeTab === 'ios' ? 'Tab Tab--on' : 'Tab'" @tap="activeTab = 'ios'">iOS 单列</text>
    </view>

    <!-- macOS 三栏：左语境域 / 中阅读区 / 右账本 -->
    <view v-if="activeTab === 'mac'" class="Mac">
      <view class="Col Col--left">
        <text class="ColTitle">语境域</text>
        <text class="Row Row--on">哲学 · 语言论</text>
        <text class="Row">管理 · 组织</text>
        <text class="Row">哲学 · 认识论</text>
      </view>

      <view class="Col Col--mid">
        <text class="ColTitle">中栏：衬线阅读区（行宽约束 34em）</text>
        <view class="Reading">
          <text class="Prose">{{ passage }}</text>
          <text class="Gloss">
            <text class="GlossTerm">language is a transparent medium</text>
            —— 直译「语言是思想的透明媒介」；母语者直觉读作「语言只是思想的载体」
          </text>
        </view>
      </view>

      <view class="Col Col--right">
        <text class="ColTitle">账本</text>
        <text class="Row">journal 128 轮</text>
        <text class="Row">错题本 7 条</text>
        <text class="Row Row--warn">离线待判 2 条</text>
      </view>
    </view>

    <!-- iOS 单列会话流 -->
    <view v-else class="IOS">
      <view class="Bubble">
        <text class="Prose Prose--ios">{{ passage }}</text>
      </view>
      <view class="Bubble Bubble--user">
        <text class="Prose Prose--ios">语言不是窗，而是思考得以演奏的乐器。</text>
      </view>
      <view :style="{ flex: 1 }" />
      <view class="InvokeBar">
        <text class="Invoke">继续</text>
        <text class="Invoke">2</text>
        <text class="Invoke">5</text>
        <text class="Invoke">15</text>
        <text class="Invoke Invoke--primary">只要听</text>
      </view>
    </view>
  </view>
</template>