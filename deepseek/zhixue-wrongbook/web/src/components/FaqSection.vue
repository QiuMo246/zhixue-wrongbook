<script setup>
const GITEE = 'https://gitee.com/qiu_moRs/zhixue-wrongbook'
const GITHUB = 'https://github.com/QiuMo246/zhixue-wrongbook'

const faqs = [
  {
    q: '我需要准备什么账号？',
    a: '一个智学网的学生账号（手机号或准考证号 + 密码）。只需要录入一次，之后会话过期会自动重新登录，不用再碰密码。',
  },
  {
    q: '会不会把我的智学网账号搞出问题？',
    a: '登录走的是智学网官方登录接口；需要验证码时它会如实报错让你稍后再试，不硬绕风控。取数只碰错题相关内容，不调用任何同学信息接口。但话说在前面：任何第三方工具用真实账号都有风险，这个决定要你自己做。',
  },
  {
    q: '支持哪些 AI 助手？',
    a: '任何支持 MCP 协议的 AI 助手都行 —— 配好 MCP 地址，它就能调用本项目的 26 个工具。安装那一步也是让 AI 助手替你完成的。',
  },
  {
    q: '我的数据存在哪？删了是真删吗？',
    a: '全在你自己电脑上：错题在本地 SQLite 数据库，图片在本机目录，登录凭据加密存进系统凭据管理器。zx_purge 是真删 —— 数据库连 WAL/SHM 一起删干净。',
  },
  {
    q: 'GitHub 打不开怎么办？',
    a: '用 Gitee。两个仓库内容完全一样，Gitee 在国内打开快、访问稳：https://gitee.com/qiu_moRs/zhixue-wrongbook 。拿不准就用 Gitee，一定不会错。',
  },
  {
    q: '换电脑怎么办？',
    a: '在新电脑上重新安装一遍、重新登录一次即可。错题数据不会自动跟着你走 —— 它只存在本机，这正是隐私的代价。',
  },
  {
    q: '错题内容会被发到网上吗？',
    a: '会发给你正在用的 AI 模型处理（题干、答案、解析、你的作答）—— 这是错因分析绕不开的一步，本项目如实告诉你，不藏着。服务端本身零云端调用；如果你连 AI 都不想让它联网，可以配本地模型，整条链路就不出你的电脑。',
  },
  {
    q: '有做不到的事吗？',
    a: '有，而且写在 README 的「已知局限」里：手写体识别有误差，看不清的会强制标记人工复核；生物、地理还没有知识点词表（能同步能选中，做不了知识点级分析）。清单在仓库 README 里，建议装之前看一眼。',
  },
]
</script>

<template>
  <section id="faq">
    <div class="wrap faq-wrap">
      <p class="kicker">常见问题</p>
      <h2 class="hf sec-title">问得最多的<span class="hl">八件事</span></h2>
      <p class="sec-lead">包括几个不太好听的答案 —— 我们更喜欢把话说在前面。</p>

      <details v-for="f in faqs" :key="f.q" class="qa">
        <summary>
          <span class="q-mark hf" aria-hidden="true">？</span>{{ f.q }}
        </summary>
        <p>{{ f.a }}</p>
      </details>
    </div>
  </section>
</template>

<style scoped>
.faq-wrap {
  max-width: 780px;
}

.qa {
  background: #fff;
  border: 1.5px solid var(--ink-faint);
  border-radius: 10px;
  margin-bottom: 10px;
  padding: 4px 18px;
}

.qa[open] {
  border-color: var(--red);
}

.qa summary {
  cursor: pointer;
  font-weight: 700;
  font-size: 16px;
  padding: 10px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.qa summary::marker {
  color: var(--red);
}

.q-mark {
  color: var(--red);
  font-size: 18px;
}

.qa p {
  margin: 2px 0 14px 34px;
  font-size: 15px;
  color: var(--ink-soft);
}
</style>
