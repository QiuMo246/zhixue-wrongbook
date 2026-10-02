<script setup>
const features = [
  {
    icon: '⇣',
    title: '错题自动同步',
    body: '把智学网里的错题拉到你电脑上，不用一页页翻卷子截图。三条通道兜底：官方导出、现成库、自建接口，一条失效还有下一条。',
  },
  {
    icon: '✎',
    title: '错因分析',
    body: 'AI 逐题判断你「为什么错」：概念没懂？算错？看漏条件？错因只许从 8 类里选，每个结论都要给出原文证据，不许瞎编。',
  },
  {
    icon: '◎',
    title: '知识点标注',
    body: '每道错题标到具体知识点。知识点只能从 341 个的受控词表里选，选不了就不硬选 —— 拒绝「看起来像」的标签。',
  },
  {
    icon: '❋',
    title: '薄弱项诊断',
    body: '先问清你「要诊断哪一科、分析哪些卷子」，再出画像。绝不拿题最多的那科替你做主，也绝不偷偷把范围扩大。',
  },
  {
    icon: '▶',
    title: '同类题练习 + 批改',
    body: '针对你错得最多的知识点出新题，做完自动批改，答案会回代验算 —— 步骤不对会指出来，不是只给你个对错。',
  },
  {
    icon: '▤',
    title: '报告导出',
    body: '错题本、练习卷、诊断报告导出成 HTML / Excel，打印出来就能刷，不用盯着屏幕复习。',
  },
]
</script>

<template>
  <section id="features">
    <div class="wrap">
      <p class="kicker">它能做什么</p>
      <h2 class="hf sec-title">错题本自己会长，<span class="hl">你只管做错它</span></h2>
      <p class="sec-lead">
        这些不是概念图，是已经写完、反复测试过的 26 个工具。
      </p>

      <div class="grid">
        <article v-for="f in features" :key="f.title" class="card feat">
          <div class="feat-icon hf" aria-hidden="true">{{ f.icon }}</div>
          <h3 class="hf">{{ f.title }}</h3>
          <p>{{ f.body }}</p>
        </article>
      </div>

      <div class="privacy card">
        <span class="p-lock" aria-hidden="true">🔒</span>
        <p>
          <strong>数据全在你自己电脑上：</strong>
          错题存本地数据库，登录凭据进系统凭据管理器，服务端不调用任何云端模型。
          有一点要说清楚：题干和答案会发给你正在用的 AI 助手处理 ——
          介意的话，可以配本地模型。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}

.feat {
  padding: 22px 22px 20px;
}

.feat:nth-child(odd) {
  transform: rotate(-0.4deg);
}

.feat:nth-child(even) {
  transform: rotate(0.4deg);
}

.feat-icon {
  width: 42px;
  height: 42px;
  border: 2px solid var(--ink);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--red);
  margin-bottom: 12px;
  background: var(--paper);
}

.feat h3 {
  font-size: 18.5px;
  margin-bottom: 8px;
}

.feat p {
  margin: 0;
  font-size: 14.5px;
  color: var(--ink-soft);
}

.privacy {
  margin-top: 30px;
  padding: 18px 22px 18px 26px;
  display: flex;
  gap: 14px;
  align-items: flex-start;
  position: relative;
}

/* 便利贴胶带：代替模板味的左侧彩条 */
.privacy::before {
  content: '';
  position: absolute;
  top: -10px;
  left: 24px;
  width: 74px;
  height: 20px;
  background: var(--yellow);
  opacity: 0.85;
  transform: rotate(-3deg);
  border-radius: 2px;
}

.privacy p {
  margin: 0;
  font-size: 15px;
}

.p-lock {
  font-size: 22px;
  line-height: 1.4;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 620px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
