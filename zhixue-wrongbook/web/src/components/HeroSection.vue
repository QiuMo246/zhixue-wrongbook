<script setup>
import { ref } from 'vue'
import { copyInstallPrompt } from '../installPrompt.js'

const copied = ref(false)

async function copyPrompt() {
  try {
    await copyInstallPrompt()
    copied.value = true
    setTimeout(() => (copied.value = false), 2500)
  } catch {
    // 剪贴板不可用（如非 HTTPS 环境）时退到安装区，用那里的降级复制
    document.getElementById('install')?.scrollIntoView({ behavior: 'smooth' })
  }
}
</script>

<template>
  <section id="top" class="hero">
    <div class="wrap hero-grid">
      <div class="hero-copy">
        <p class="kicker">给初中生的错题本外挂</p>
        <h1 class="hf hero-title">
          把智学网的错题，<br />
          变成你的<span class="hl">专属练习卷</span>
        </h1>
        <p class="hero-sub">
          同步错题、分析错因、找出最弱的那个知识点、出同类题给你练、做完自动批改
          —— 这些活，交给你的 AI 助手。<strong>数据全在你自己电脑上。</strong>
        </p>
        <div class="hero-actions">
          <button class="btn btn-red" type="button" @click="copyPrompt">
            {{ copied ? '✓ 已复制！' : '复制安装提示词' }}
          </button>
        </div>
        <p class="hero-hint">
          {{ copied
            ? '打开你的 AI 助手，粘贴发送 —— 剩下的它替你装好。'
            : '不用自己去 Gitee 下载配置：复制这段话发给 AI 助手，它替你装好。' }}
        </p>
        <ul class="badges">
          <li><strong>8 类</strong>错因枚举</li>
          <li><strong>341 个</strong>知识点</li>
        </ul>
      </div>

      <div class="hero-visual" aria-hidden="true">
        <div class="nb nb-back hf">×</div>
        <div class="nb nb-front">
          <div class="nb-head">物理 · 午练 · 第 9 题 <span class="nb-score">得 0 / 3 分</span></div>
          <p class="nb-q">
            一块冰完全熔化成水后，质量 <span class="hl">变小了吗</span>？密度呢？
          </p>
          <div class="nb-note">
            <span class="nb-circle">✓</span>
            <div>
              <p class="nb-why"><strong>错因：概念混淆</strong> —— 把「状态变化」当成了「质量变化」</p>
              <p class="nb-fix">知识点：质量是物体的属性，不随形状、状态改变 → 已出 3 道同类题</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero {
  padding: 64px 0 76px;
}

.hero-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 48px;
  align-items: center;
}

.hero-title {
  font-size: clamp(34px, 5vw, 56px);
  margin: 6px 0 18px;
}

.hero-sub {
  color: var(--ink-soft);
  font-size: 17.5px;
  max-width: 520px;
  margin: 0 0 28px;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 12px;
}

.hero-hint {
  margin: 0 0 26px;
  font-size: 14px;
  color: var(--ink-soft);
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 26px;
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 14px;
  color: var(--ink-soft);
}

.badges strong {
  color: var(--red);
  font-size: 18px;
  margin-right: 4px;
  font-family: var(--font-head);
}

/* ---- 右侧错题本卡片 ---- */
.hero-visual {
  position: relative;
  min-height: 380px;
}

.nb {
  position: absolute;
  background: #fff;
  border: 1.5px solid var(--ink-faint);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
  background-image:
    linear-gradient(rgba(58, 123, 213, 0.09) 1px, transparent 1px);
  background-size: 100% 26px;
}

.nb-back {
  width: 130px;
  height: 130px;
  right: 6px;
  top: -14px;
  transform: rotate(8deg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 72px;
  color: var(--red);
  border: 2.5px solid var(--red);
}

.nb-front {
  left: 0;
  right: 26px;
  top: 44px;
  padding: 20px 22px 18px;
  transform: rotate(-1.6deg);
}

.nb-head {
  font-size: 13px;
  font-weight: 700;
  color: var(--blue);
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.nb-score {
  color: var(--red);
}

.nb-q {
  font-size: 16.5px;
  margin: 12px 0 14px;
}

.nb-note {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  border-top: 1.5px dashed var(--ink-faint);
  padding-top: 12px;
}

.nb-circle {
  flex: none;
  width: 34px;
  height: 34px;
  border: 2.5px solid var(--red);
  border-radius: 50%;
  color: var(--red);
  font-weight: 900;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  transform: rotate(-8deg);
}

.nb-why {
  margin: 0 0 4px;
  font-size: 14.5px;
}

.nb-why strong {
  color: var(--red);
}

.nb-fix {
  margin: 0;
  font-size: 13px;
  color: var(--ink-soft);
}

@media (max-width: 900px) {
  .hero-grid {
    grid-template-columns: 1fr;
  }

  .hero-visual {
    max-width: 460px;
    min-height: 330px;
  }
}
</style>
