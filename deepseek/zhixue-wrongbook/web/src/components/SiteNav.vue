<script setup>
const GITEE = 'https://gitee.com/qiu_moRs/zhixue-wrongbook'
</script>

<template>
  <header class="nav">
    <div class="wrap nav-row">
      <a class="brand hf" href="#top">智学网错题助手</a>
      <nav class="links">
        <a href="#features">功能</a>
        <a href="#install">安装</a>
        <a href="#demo">用起来什么样</a>
        <a href="#faq">常见问题</a>
      </nav>
      <a class="btn btn-red nav-cta" :href="GITEE" target="_blank" rel="noopener">
        Gitee 安装
      </a>
    </div>
  </header>
</template>

<style scoped>
.nav {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(251, 250, 246, 0.92);
  backdrop-filter: blur(6px);
  border-bottom: 1.5px solid var(--ink-faint);
}

.nav-row {
  display: flex;
  align-items: center;
  gap: 22px;
  height: 62px;
}

.brand {
  font-size: 19px;
  color: var(--ink);
  text-decoration: none;
  white-space: nowrap;
}

.links {
  display: flex;
  gap: 18px;
  margin-left: auto;
  font-size: 14.5px;
}

.links a {
  color: var(--ink-soft);
  text-decoration: none;
}

.links a:hover {
  color: var(--red);
}

.nav-cta {
  padding: 8px 18px;
  font-size: 14.5px;
  white-space: nowrap;
}

@media (max-width: 760px) {
  .links { display: none; }
  .nav-cta { margin-left: auto; }
}
</style>
