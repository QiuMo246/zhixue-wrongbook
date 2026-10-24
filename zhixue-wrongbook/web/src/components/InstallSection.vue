<script setup>
import { ref } from 'vue'
import { AI_PROMPT, copyInstallPrompt } from '../installPrompt.js'

const GITHUB = 'https://github.com/QiuMo246/zhixue-wrongbook'
// 国内加速镜像（前缀 + 完整 GitHub 地址）。第三方公益代理，
// 2026-10-24 实测可用；挂了就用 GitHub 直连。
const MIRROR = 'https://gh-proxy.org/'
const MIRROR_ALT = 'https://gh-proxy.com/'

const copied = ref(false)

async function copyPrompt() {
  try {
    await copyInstallPrompt()
    copied.value = true
  } catch {
    // 剪贴板不可用时退化：选中文本让用户手动 Ctrl+C
    const el = document.getElementById('ai-prompt-text')
    const range = document.createRange()
    range.selectNodeContents(el)
    const sel = window.getSelection()
    sel.removeAllRanges()
    sel.addRange(range)
  }
  setTimeout(() => (copied.value = false), 2000)
}

const manualSteps = [
  { t: '装依赖', d: 'python -m venv .venv，再用它 pip install -r requirements.txt' },
  { t: '跑验收', d: '依次运行 tools/acceptance.py、tools/edge_test.py、tools/mcp_e2e.py，全部通过就说明装对了，不需要联网' },
  { t: '登录', d: '运行 tools/login.py，在弹出的专用浏览器里登录一次（含验证码）' },
  { t: '接 AI', d: '在 AI 助手的 MCP 配置里加上 server.py，信任自定义连接器' },
  { t: '装编排 Skill', d: '把 skill/zhixue-wrongbook/ 复制到 AI 的 skills 目录，说「帮我整理错题」它就知道怎么干' },
]
</script>

<template>
  <section id="install">
    <div class="wrap">
      <p class="kicker">怎么安装</p>
      <h2 class="hf sec-title">源码在 <span class="hl">GitHub</span>，国内走镜像加速</h2>
      <p class="sec-lead">
        GitHub 国内直连经常超时。不用你操心 —— 安装时会自动换镜像。
      </p>

      <!-- 为什么要镜像：从零解释 -->
      <div class="explain card">
        <p>
          这个项目的源码放在 <strong>GitHub</strong>（国外的代码托管网站）。
          国内直连它经常转圈甚至打不开，所以准备了<strong>镜像加速</strong>：
          由第三方站点替你从 GitHub 取文件，再从国内发给你，速度稳得多。
          <strong>两条通道内容完全一样</strong>，用哪个都行。
        </p>
      </div>

      <div class="vs-grid">
        <div class="card repo mirror">
          <p class="rec hf">✓ 默认推荐</p>
          <h3 class="hf">镜像加速</h3>
          <ul>
            <li class="mark-yes-p">国内直连，不用翻墙</li>
            <li class="mark-yes-p">一条挂了自动换下一条</li>
          </ul>
          <p class="who">→ 绝大多数情况用这个，复制提示词就行</p>
          <button class="btn btn-red" type="button" @click="copyPrompt">
            {{ copied ? '✓ 已复制！' : '复制安装提示词' }}
          </button>
        </div>

        <div class="card repo github">
          <h3 class="hf">GitHub 直连</h3>
          <ul>
            <li>官方原站，代码、提交记录、Issue 都在这</li>
            <li>国内直连不稳，海外或挂了代理时最快</li>
          </ul>
          <p class="who">→ 想自己看源码、提问题，来这里</p>
          <a class="btn btn-ghost" :href="GITHUB" target="_blank" rel="noopener">去 GitHub 仓库</a>
        </div>
      </div>

      <p class="verdict">
        拿不准？<strong>用镜像，一定不会错。</strong>
      </p>

      <!-- 懒人安装法 -->
      <div class="lazy card">
        <div class="lazy-head">
          <h3 class="hf">懒人安装法（推荐）</h3>
          <p>把下面这段话<strong>原样复制给你的 AI 助手</strong>，剩下的它替你干。
            账号密码只输在弹出的<strong>专用浏览器</strong>里 —— 不进命令行、不进聊天记录。</p>
        </div>
        <div class="prompt-box">
          <div class="prompt-bar">
            <span>复制给 AI 助手</span>
            <button class="btn btn-copy" type="button" @click="copyPrompt">
              {{ copied ? '✓ 已复制' : '复制全文' }}
            </button>
          </div>
          <pre id="ai-prompt-text">{{ AI_PROMPT }}</pre>
        </div>
      </div>

      <!-- 手动安装 -->
      <details class="manual">
        <summary class="hf">自己动手装？展开五步手动安装</summary>
        <ol class="steps">
          <li v-for="(s, i) in manualSteps" :key="s.t">
            <span class="step-no hf">{{ i + 1 }}</span>
            <div>
              <strong>{{ s.t }}</strong>
              <p>{{ s.d }}</p>
            </div>
          </li>
        </ol>
        <p class="manual-more">
          第一步拿代码（没装 git 就改用 <code>install.py --from-zip</code>）：
          <br><code class="cmd">git clone {{ MIRROR }}{{ GITHUB }}</code>
          <br>这条不通就换：<code class="cmd">git clone {{ MIRROR_ALT }}{{ GITHUB }}</code>
          <br>完整命令和注意事项见仓库里的
          <a :href="GITHUB + '#readme'" target="_blank" rel="noopener">README.md</a>。
        </p>
      </details>
    </div>
  </section>
</template>

<style scoped>
.explain {
  padding: 18px 24px;
  margin-bottom: 24px;
  position: relative;
}

/* 铅笔蓝回形针角标：代替模板味的左侧彩条 */
.explain::before {
  content: '30 秒小课堂';
  position: absolute;
  top: -12px;
  left: 18px;
  background: var(--blue);
  color: #fff;
  font-size: 12.5px;
  font-weight: 700;
  padding: 2px 12px;
  border-radius: 999px;
  letter-spacing: 0.05em;
}

.explain p {
  margin: 0;
  font-size: 16px;
}

.vs-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.repo {
  padding: 24px;
}

.repo.mirror {
  border: 2px solid var(--red);
  transform: rotate(-0.5deg);
}

/* 手动安装里的命令：等宽、可换行，别撑破卡片 */
.cmd {
  display: inline-block;
  margin: 4px 0;
  padding: 3px 8px;
  background: #f2f0e8;
  border-radius: 5px;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12.5px;
  word-break: break-all;
}

.repo.github {
  transform: rotate(0.5deg);
}

.rec {
  display: inline-block;
  background: var(--yellow);
  padding: 2px 12px;
  border-radius: 6px;
  font-size: 14px;
  margin-bottom: 10px;
  transform: rotate(-1deg);
}

.repo h3 {
  font-size: 24px;
  margin-bottom: 10px;
}

.repo ul {
  margin: 0 0 10px;
  padding-left: 20px;
  font-size: 15px;
  color: var(--ink-soft);
}

.repo .who {
  font-size: 14px;
  color: var(--ink);
  background: var(--paper);
  border-radius: 8px;
  padding: 8px 12px;
  margin: 0 0 16px;
}

.verdict {
  text-align: center;
  font-size: 18px;
  margin: 26px 0 40px;
}

.verdict strong {
  color: var(--red);
  border-bottom: 3px solid var(--yellow);
}

/* ---- 懒人安装 ---- */
.lazy {
  padding: 26px;
}

.lazy-head h3 {
  font-size: 21px;
  margin-bottom: 6px;
}

.lazy-head p {
  margin: 0 0 18px;
  color: var(--ink-soft);
  font-size: 15px;
}

.prompt-box {
  border: 1.5px solid var(--ink);
  border-radius: 10px;
  overflow: hidden;
}

.prompt-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--ink);
  color: #fff;
  padding: 8px 14px;
  font-size: 13.5px;
}

.prompt-box pre {
  margin: 0;
  padding: 16px 18px;
  background: #fff;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
}

/* ---- 手动安装 ---- */
.manual {
  margin-top: 26px;
  background: #fff;
  border: 1.5px dashed var(--ink-faint);
  border-radius: 12px;
  padding: 16px 22px;
}

.manual summary {
  cursor: pointer;
  font-size: 17px;
  color: var(--blue);
}

.manual summary::marker {
  color: var(--red);
}

.steps {
  list-style: none;
  padding: 0;
  margin: 18px 0 8px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 28px;
}

.steps li {
  display: flex;
  gap: 12px;
}

.step-no {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 2px solid var(--red);
  color: var(--red);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}

.steps p {
  margin: 2px 0 0;
  font-size: 14px;
  color: var(--ink-soft);
}

.manual-more {
  font-size: 14px;
  color: var(--ink-soft);
}

@media (max-width: 760px) {
  .vs-grid,
  .steps {
    grid-template-columns: 1fr;
  }
}
</style>
