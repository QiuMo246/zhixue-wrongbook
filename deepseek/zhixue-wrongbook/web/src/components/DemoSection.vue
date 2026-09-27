<script setup>
// 演示对话基于真实流程编排：诊断闸门（先问科目+范围）是真实存在的行为，
// 数字为示意，页面上已标注「示意」。
const turns = [
  { who: 'me', text: '帮我同步错题' },
  {
    who: 'ai',
    text: '已同步 27 道错题：数学 11 · 物理 9 · 英语 7，含题干、答案、解析和你的得分。要我逐题分析错因吗？',
  },
  { who: 'me', text: '先来个物理的个性化诊断' },
  {
    who: 'ai',
    text: '好，先确认两件事：① 科目是物理，对吗？② 分析哪些卷子？你近两周物理有：午练 ×4、周测 ×1、晚练 ×3。',
    stamp: '诊断闸门：不问清范围，不给数据',
  },
  { who: 'me', text: '对，午练和周测，本周的' },
  {
    who: 'ai',
    text: '只统计本周物理午练 + 周测，共 9 道错题。最薄弱的是「浮力与密度」：4 道全错在单位换算。已生成 5 题同类练习卷，导出成 HTML 打开就能做。',
  },
  { who: 'me', text: '做完了，帮我批改' },
  {
    who: 'ai',
    text: '批改完成：4 对 1 错。错的那道是公式记混了（阿基米德原理 vs 称重法）—— 已回错题本，并更新了你的薄弱点画像。下次同步时分析结果不会被清掉。',
  },
]
</script>

<template>
  <section id="demo">
    <div class="wrap">
      <p class="kicker">用起来什么样</p>
      <h2 class="hf sec-title">一段对话，<span class="hl">错题本就转起来了</span></h2>
      <p class="sec-lead">
        下面是真实流程的示意（数字为示例）：你会注意到助手在出诊断前先问你两件事 ——
        这是写死在程序里的规矩，不是它心情好才问。
      </p>

      <div class="chat card" aria-label="使用流程示意对话">
        <template v-for="(t, i) in turns" :key="i">
          <div :class="['bubble', t.who]">
            <span v-if="t.stamp" class="stamp hf">{{ t.stamp }}</span>
            <p>{{ t.text }}</p>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat {
  max-width: 720px;
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background-image: linear-gradient(rgba(30, 42, 68, 0.035) 1px, transparent 1px);
  background-size: 100% 28px;
}

.bubble {
  max-width: 82%;
  padding: 10px 16px;
  border-radius: 12px;
  position: relative;
  font-size: 15px;
}

.bubble p {
  margin: 0;
}

.bubble.me {
  align-self: flex-end;
  background: rgba(58, 123, 213, 0.12);
  border: 1.5px solid rgba(58, 123, 213, 0.35);
  border-bottom-right-radius: 3px;
}

.bubble.ai {
  align-self: flex-start;
  background: #fff;
  border: 1.5px solid var(--ink-faint);
  border-bottom-left-radius: 3px;
}

.stamp {
  display: inline-block;
  font-size: 12px;
  color: var(--red);
  border: 1.5px solid var(--red);
  border-radius: 6px;
  padding: 1px 8px;
  margin-bottom: 6px;
  transform: rotate(-2deg);
  letter-spacing: 0.06em;
}
</style>
