<script setup>
const GITEE = 'https://gitee.com/qiu_moRs/zhixue-wrongbook'
const GITHUB = 'https://github.com/QiuMo246/zhixue-wrongbook'
</script>

<template>
  <footer class="foot">
    <div class="wrap foot-grid">
      <div>
        <p class="hf brand">智学网错题助手</p>
        <p class="fine">
          开源、免费、本地运行。错题的题干会发给你使用的 AI 模型处理，介意请配本地模型。
        </p>
      </div>
      <div class="foot-links">
        <a :href="GITEE" target="_blank" rel="noopener">Gitee 仓库（国内直达）</a>
        <a :href="GITHUB" target="_blank" rel="noopener">GitHub 仓库</a>
        <a :href="GITHUB + '/blob/main/README.md#已知局限诚实清单'" target="_blank" rel="noopener">已知局限（诚实清单）</a>
      </div>
    </div>
    <div class="wrap">
      <p class="fine copy">拿不准就用 Gitee：https://gitee.com/qiu_moRs/zhixue-wrongbook</p>
    </div>
  </footer>
</template>

<style scoped>
.foot {
  border-top: 2px dashed var(--ink-faint);
  padding: 40px 0 32px;
  background: #fff;
}

.foot-grid {
  display: flex;
  gap: 40px;
  justify-content: space-between;
  flex-wrap: wrap;
}

.brand {
  font-size: 18px;
  margin-bottom: 6px;
}

.fine {
  font-size: 13.5px;
  color: var(--ink-soft);
  margin: 0;
  max-width: 460px;
}

.foot-links {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 14.5px;
}

.copy {
  margin-top: 26px;
}
</style>
