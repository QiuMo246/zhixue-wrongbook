# -*- coding: utf-8 -*-
"""生成语文错题报告：一份 Markdown + 一份带交互的 HTML。

内容只在 DATA 里写一次，两种格式共用，不会对不上。
"""
import html
import re
from pathlib import Path

OUT_DIR = Path(r"D:\Data\Desktop\aaaaa\555")
ASSETS = OUT_DIR / "assets"

# ---------------------------------------------------------------- 数据
WEEK = [
    ("10-16", "第七周语文周测", "周测", 79, 100),
    ("10-13", "《传记》写作", "晚练", 92, 100),
    ("10-15", "《背影》第一课时", "晚练", 94, 100),
    ("10-19", "《背影》第二课时", "晚练", 95, 100),
]

# 失分类型
LOSS = [
    ("主观题要点不全", 19, 47.5),
    ("作文文体缺失", 8, 20.0),
    ("记忆性错误", 7, 17.5),
    ("选择题", 6, 15.0),
]

# 每场卷子下的错题
CARDS = [
    # ---------------- 周测 ----------------
    dict(
        sec="zt", no="第 2、6 题", kind="单项选择", full=6, got=0,
        img="zt_a.jpg",
        wrote="第 2 题选 D，第 6 题选 C，均判错。",
        miss=[("题干定位", "❌", "答题卡只回传填涂结果，没有题干和选项，**具体考点无法确定**")],
        answer="这两题我没法给你答案——没有选项就没有分析依据。把题干和四个选项拍给我，我按选项逐项拆。",
        ideas=[
            ("1 圈限定词", "是「正确」还是「**不正确**」，是「加点字」还是「词语」", "圈错这一步，后面全白做"),
            ("2 回原文", "每个选项都要能在原文/课本找到对应句", "找不到对应句 = 高风险项，先标记"),
            ("3 查陷阱", "绝对化（都/一定/唯一）、偷换范围、因果倒置", "三类陷阱覆盖 80% 错项"),
            ("4 字音字形", "拿不准的字放回另一个常见词里读", "「载重」zài /「记载」zǎi"),
            ("5 二选一", "排除确定错的两个，比「哪个改动更小」", "出题人一般只改一处"),
        ],
    ),
    dict(
        sec="zt", no="第 8 题", kind="古诗炼字比较", full=3, got=1,
        img="zt_b.jpg",
        wrote="认为「破」更贴切；「苦」「疏篱空」渲染悲苦气氛，「破」指打破，更能渲染愁苦；换「生」不能体现孤苦。",
        miss=[
            ("释字义", "半", "只写「打破」，没落到句中具体对象"),
            ("描画面", "❌", "**完全没把字还原成画面**"),
            ("点手法", "❌", "**没有任何手法术语**，硬扣分点"),
            ("析情感", "半", "「愁苦的气氛」说了两遍，没说是谁的愁"),
            ("做比较", "半", "只说「不能体现孤苦」，没说出差别在哪"),
        ],
        answer="「破」字更贴切。「破」是「打破、使残缺」的意思，写灯被打破、光焰将尽，画面由静转动，一盏残灯照着一个孤身的人，景象凄清。一个「破」字以动写静，把灯火的残败与处境的破败、心境的破碎叠在一起，与「苦」「孤」呼应，愁苦之情不言自明。若换成「生」，只是写灯自然地亮起来，是常态、平直，没有力度，也承载不了「愁苦」的分量。",
        ideas=[
            ("1 释", "解释句中义，不是字典义", "「X」字是……的意思，这里指……"),
            ("2 描", "放回句子，还原画面", "它写出了……（谁+做什么+什么景象）"),
            ("3 手", "拟人／化静为动／以动写静／叠词", "运用……手法，把……写得……"),
            ("4 情", "落到谁的情感", "表达了……（谁）……的情感"),
            ("5 比", "比较题才写，说清另一个字差在哪", "若换成「Y」，只能写出……，缺少……"),
        ],
    ),
    dict(
        sec="zt", no="第 9 题", kind="文言断句", full=3, got=2,
        img="zt_b.jpg",
        wrote="昔永嘉乱 / 土人登此避贼 / **守之** / 经年食尽",
        miss=[("第三处", "❌", "断早了。「守之经年」是**动补结构**，补语「经年」不能拆出去")],
        answer="昔永嘉乱，土人登此避贼，守之经年，食尽。\n译：从前永嘉之乱时，当地人登上这里躲避贼人，守住它好几年，粮食吃完了。",
        ideas=[
            ("1 先翻译", "整句译成白话，哪里该停一读就出来", "最可靠，比背虚词管用"),
            ("2 看语法", "主谓之间、动宾之间不能断；**动补不能拆**", "「守之」+「经年」"),
            ("3 看虚词", "「者、也、矣、耳」后断；「之、而、以」前多不断", "「之」后不断"),
            ("4 看句意", "每段要能独立成句", "「经年食尽」讲不通"),
            ("5 自检", "把每段单独读一遍，有一截读不通就是断错", "你这题断完就能发现"),
        ],
    ),
    dict(
        sec="zt", no="第 11 题", kind="文言实词「绝」", full=8, got=6,
        img="zt_b.jpg",
        wrote="皆险绝=④　冷冷不绝=③　隐映如绝=①　沿溯阻绝=②（4 空错 1 空）",
        miss=[("课文锚点", "❌", "凭现代汉语语感猜，没用《三峡》里学过的三个「绝」当模板，导致两个义项挤在一起乱配")],
        answer="沿溯阻绝＝隔断、断绝（航道被阻断）｜冷冷不绝＝停止、消失（声音不断）｜皆险绝＝极、非常（山势极险）｜隐映如绝＝似断非断（若隐若现）。\n\n「绝」五义：① 断绝（沿溯阻绝）② 停止（哀转久绝）③ 极／非常（绝𪩘、险绝）④ 与世隔绝（绝境）⑤ 独一无二（绝妙）。",
        ideas=[
            ("1 想课内", "这词在课文中出现过几次，各是什么意思", "课内打底，课外迁移"),
            ("2 代入", "把义项代进句子读一遍", "唯一标准是「代入后句意通顺」"),
            ("3 排除", "先填最有把握的，剩下自然归位", "别硬猜"),
        ],
    ),
    dict(
        sec="zt", no="第 12 题", kind="引诗作用", full=6, got=3,
        img="zt_c.jpg",
        wrote="第一处「渲染悲凉气氛，体现三峡空旷广阔」；第二处「被大赦的喜悦，渲染欢快氛围」。",
        miss=[
            ("第一处", "半", "「悲凉」和「空旷广阔」**自相矛盾**——前者是情感，后者是空间"),
            ("第二处", "✅", "这处基本到位"),
            ("两处对比", "❌", "**完全没写**，这是本题最大的点，等于把 6 分题当两个 3 分题做"),
        ],
        answer="① 引用《三峡》渔者歌「巴东三峡巫峡长，猿鸣三声泪沾裳」，用猿声的凄厉渲染三峡秋日萧瑟凄清的氛围，写出三峡的险峻与行旅的悲苦，表达作者的悲悯。② 引用李白「两岸猿声啼不住，轻舟已过万重山」，写遇赦东归时猿声相伴、轻舟疾行，表现如释重负、欢快喜悦。③ 两处**同写猿声而情感相反**，一悲一喜形成对比，说明「一切景语皆情语」——景随情变，既丰富文化底蕴，也使情感更有层次。",
        ideas=[
            ("1 写", "诗句本身写了什么", "引用……的诗句，写出了……（意象+画面）"),
            ("2 关", "和上下文什么关系", "对比／照应／铺垫／佐证。**见「两处」「分别」必答对比**"),
            ("3 情", "表达什么情感或主旨", "渲染了……氛围，表达了……之情"),
        ],
    ),
    dict(
        sec="zt", no="第 14 题", kind="标题作用", full=4, got=3,
        img="zt_c.jpg",
        wrote="①线索贯穿全文 ②设悬念 ③父亲照看树、树回报父亲，点明中心 ④点明写作对象",
        miss=[
            ("重复", "❌", "第 ④ 点和第 ① 点说的是同一件事，**4 条只有 3 条有效**"),
            ("象征", "❌", "父亲与树相互扶持、彼此成就，这层象征义一个字没提"),
        ],
        answer="① 内容：点明写作对象——父亲和那棵苹果树。② 结构：双线并行，作为线索贯穿全文。③ 手法：运用象征，父亲与树相互扶持、彼此成就，树是父亲生命的一部分，父亲也是树生长的依靠。④ 情感：寄托父亲对树的深情，也写出树对父亲的回报，暗含感恩与不舍。⑤ 主旨效果：揭示「人与土地相互滋养」的主旨；把两个看似无关的事物并置，设悬念，引发阅读兴趣。",
        ideas=[
            ("内", "点明什么对象／环境", "点明写作对象……"),
            ("结", "是不是线索，有没有铺垫照应", "作为线索贯穿全文……"),
            ("手", "双关／象征／比喻／化用／悬念", "运用……手法"),
            ("情", "寄托什么感情", "寄托了……之情"),
            ("主", "暗示什么主旨，对读者什么作用", "暗示……主旨，引发读者……"),
            ("查重", "回头扫一眼，有没有两条在说同一件事", "重复的点不给第二分"),
        ],
    ),
    dict(
        sec="zt", no="第 15 题", kind="句子赏析", full=6, got=5,
        img="zt_d.jpg",
        wrote="（1）连用动词写父亲照料树的过程，体现用心细致，短词连用有节奏美。（2）比喻，木屑比作「对父亲说的话」，写树的不舍，侧面体现感情深厚。",
        miss=[("情感落点", "❌", "停在「用心、细致」（动作层），没写「他把树当亲人」（形象层）。**你 4 次赏析题，4 次都停在这一步**")],
        answer="（1）连用「流水」「摘袋」等动词短语，把父亲照料苹果树的过程写得连贯而有条理，动作精准、节奏明快，既表现劳作的娴熟细致，更写出他把树当亲人般疼惜的深情，字里行间是作者的敬意。（2）运用比喻，把「清香的木屑」比作「对父亲说的话」，赋予木屑以人的情感，生动写出树被砍倒时的不舍，侧面表现父亲与树之间深厚的情感，含蓄动人。",
        ideas=[
            ("1 手", "修辞／描写／句式／用词", "运用……手法"),
            ("2 内", "写出了什么内容", "生动形象地写出了……"),
            ("3 效", "表达效果", "增强了……，富有……"),
            ("4 情", "**作者／人物的情感，或人物形象**", "表现了……（谁）……的情感／是个……的人"),
        ],
    ),
    dict(
        sec="zt", no="第 16 题", kind="人物形象", full=6, got=4,
        img="zt_d.jpg",
        wrote="①细心勤劳（施肥套袋摘袋）②重感情、内心细腻（砍树时不舍）③年老体衰（年近 80，挪几下袋子就气喘）",
        miss=[
            ("点数", "❌", "只写 3 点，6 分题要 4 点"),
            ("方向", "❌", "「年老体衰」是生理状态，**不是性格品质**，这条基本不得分"),
            ("第 4 点", "❌", "缺「质朴坚韧／坚守土地」——年近八十仍不肯闲下来"),
        ],
        answer="① 勤劳能干：长年侍弄果树，从施肥、套袋到摘袋样样亲力亲为，一刻也闲不住。② 细致耐心：照料果树一丝不苟，动作轻缓，像对待孩子一样。③ 重情重义：砍树时内心充满不舍与悲伤，把树当作有生命的亲人。④ 质朴坚韧、坚守土地：年近八十仍不肯离开果园，在贫瘠土地上坚持耕作，是传统农民对土地的深情与执着。",
        ideas=[
            ("1 找", "圈出动作、语言、神态、心理、他人评价", "这是全部素材"),
            ("2 提炼", "每个素材问「说明他什么品质」，用 2～4 字命名", "勤劳、善良、坚韧、节俭"),
            ("3 成句", "概括词 + 文本依据 + 他是个什么人", "一点一句，4 点写满"),
            ("筛选", "只写品质类；年龄、外貌、身体好坏不算形象", "「年近八十还下地」证明的是勤劳，不是「他老了」"),
        ],
    ),
    dict(
        sec="zt", no="第 17 题", kind="结尾/主旨启示", full=6, got=5,
        img="zt_d.jpg",
        wrote="①父亲知道树会重新长出 ②新旧交替的哲理，「生命力顽强」「生生不息」 ③不能片面看轻事物 ④树带给人希望，应看到好的一面",
        miss=[
            ("有效点", "❌", "**4 条只有 3 条有效**"),
            ("重复", "❌", "② 里「生命力顽强」和「生生不息」是同义；③「努力向上」和 ④「抱有希望」重叠"),
        ],
        answer="① 内容层：老树被砍、新枝又发，写出父亲对树的了解，也写出他对生命规律的顺应。② 哲理层：旧去新来、生生不息，揭示生命的韧性与循环。③ 人物层：父亲在贫瘠土地上坚持耕作，表现劳动人民坚韧乐观的精神。④ 启示层：看待事物不能片面，身处困境也要向上生长、心怀希望。",
        ideas=[
            ("内容", "这句话写了什么", "这句话写出了……"),
            ("哲理", "说明什么道理", "揭示了……的道理"),
            ("人物", "表现了谁的精神", "表现了……的精神"),
            ("启示", "我该怎么做", "这启示我们……"),
            ("合并检查", "任意两条能不能合并成一句", "能合并就是重复，删一条补新层"),
        ],
    ),
    # ---------------- 晚练 ----------------
    dict(
        sec="wl", no="1013 作文", kind="小传写作", full=30, got=22,
        img="wl1013.jpg",
        wrote="《同学小传》：四年级相识 → 一起放学 → 校运会 1000 米摔倒又站起 → 引用「我言秋日胜春朝」升华。",
        miss=[
            ("身份信息", "❌", "**通篇没有他的名字、年龄、身份**"),
            ("时间线", "半", "只有「四年级」和「校运会」两个点，中间几年是空的"),
            ("典型事例", "半", "只有一个事例，而且写成「事件过程」，不是「性格证据」"),
            ("概括评价", "半", "结尾只有「坚韧」一个词"),
            ("传记语言", "❌", "大量抒情、四字短语堆砌"),
        ],
        answer="缺身份 →「他叫×××，今年十四岁，是我初二（3）班的同班同学。个子不高，走路总低着头，说话前先笑一下——认识他的人都说，他身上有股『慢火』。」\n缺时间线 →「他四年级从外地转来，因家里人生病才搬到这座城市；初一我们成了同桌；初二他当上了体育委员。」\n缺评价 →「他就是这么一个人：不声张，不诉苦，摔倒了就自己站起来。认识他之后我才明白，所谓坚韧，不是喊出来的，是一次次默默站起来攒出来的。」",
        ideas=[
            ("1 定文体", "题目出现「传／小传／传记」→ 写传记体", "**记叙文写「一件事怎么发生」，小传写「一个人怎么长成这样的」**"),
            ("2 列提纲", "① 身份定位 ② 来历背景 ③ 核心事例（详写）④ 次要事例（略写）⑤ 评价收束", "五个格子填满再动笔"),
            ("3 配比", "核心事例 50%，背景和次要各 15%，开头结尾各 10%", "你现在是一个事例占 1/3，其余全是抒情"),
            ("4 降调", "传记以叙述为主，四字短语一段最多一个", "写具体的东西：「梧桐叶落在跑道上，被鞋底碾出脆响」"),
            ("5 自查", "他是谁？他经历过什么？他是个什么样的人？", "三句都答上才算「传」"),
        ],
    ),
    dict(
        sec="wl", no="1015 第2题(1)", kind="填空梳理", full=6, got=4,
        img="wl1015.jpg",
        wrote="① 内心的匮乏　② **漫步写字**　③ 老屋的院子里",
        miss=[("第 ② 空", "❌", "原文是「漫步**阡陌**」。不是理解问题，是**凭印象写、没回原文找**")],
        answer="① 内心的匮乏　② 漫步阡陌　③ 老屋的院子里",
        ideas=[
            ("1 划句", "按题干关键词在原文找对应句", "「漫步」「篱笆」"),
            ("2 逐字抄", "只抄原文的词", "**不许意译、不许改写**"),
            ("3 验字数", "格子长短往往暗示字数", "字数不对就再找一遍"),
        ],
    ),
    dict(
        sec="wl", no="1015 第2题(2)", kind="加点词赏析", full=5, got=4,
        img="wl1015.jpg",
        wrote="拟人，「踮起脚」写出父亲松土让植物破土而出、茁壮成长，展现生机勃勃，体现父亲爱护植物，增强生动性。",
        miss=[("情感落点", "❌", "只缺一层：**作者自己的情感**。老师批注就两个字——「作者的欣喜」")],
        answer="「踮起脚」运用拟人，把花草庄稼当作有生命、懂疼惜的孩子，生动写出父亲松土时的小心翼翼与温柔，表现园中植物的蓬勃生机，既写出父亲对植物的爱护，也透出**作者目睹这一幕时的欣喜与感动**，增强了文章的生动性与感染力。",
        ideas=[
            ("1 释", "这个词在句中什么意思", "「踮起脚」＝脚跟抬起，动作很轻"),
            ("2 描", "写出什么动作、什么画面", "生动写出……"),
            ("3 手", "拟人／细节描写／反复", "运用……手法"),
            ("4 情", "谁的情感，或他是个什么人", "表现了……，透出作者的……"),
        ],
    ),
    dict(
        sec="wl", no="1015 第2题(4)", kind="标题作用", full=6, got=3,
        img="wl1015.jpg",
        wrote="①象征父亲淳朴的感情 ②化用陶渊明「采菊东篱下」，表达赞美 ③与「我」没有东篱对比，突出内心匮乏 ④以「我的矮」指「无数种庄稼的父亲们」",
        miss=[
            ("结构", "❌", "**没写「作为线索贯穿全文、虚实结合」**"),
            ("效果", "❌", "**没写「暗示主旨、引发读者联想」**"),
        ],
        answer="① 表层：「东篱」指父亲亲手修整的菜园篱笆，是具体可感的物象。② 文化层：化用陶渊明「采菊东篱下」，赋予父亲和这片田园以诗意与文化内涵。③ 对比：与「我」「没有东篱」形成对比，突出「我」内心的匮乏与都市人的失落。④ 象征：「东篱」象征田园生活，也指「无数种庄稼的父亲们」。⑤ 结构：作为线索贯穿全文，虚实结合（眼前的篱笆 + 心中的田园）。⑥ 效果：暗示文章主旨，引发读者对「东篱」意蕴的丰富联想。",
        ideas=[
            ("内结手情主", "同第 14 题的五角度", "一个角度一条，别重复"),
            ("加文化层", "标题含典故时，必须单列「文化内涵」", "化用／出处／象征义"),
            ("送分项", "结构和效果你每次都不写", "这两条最容易拿"),
        ],
    ),
    dict(
        sec="wl", no="1019 第2题(1)", kind="开头作用", full=3, got=None,
        img="wl1019.jpg",
        wrote="①点明时间、地点 ②「笔与纸」照应标题 ③引出下文对父亲写毛笔字的回忆",
        miss=[
            ("内容", "❌", "「点明时间、地点」**不是记叙文开头作用的得分点**（那是说明文、新闻的考点）"),
            ("氛围", "❌", "春日午后教室练字，营造的是安静温馨的氛围"),
            ("效果", "❌", "以声音入笔、画面感强、引发兴趣"),
        ],
        answer="内容上：交代春日午后在教室练字的情景，营造安静、温馨的氛围。结构上：由「笔与纸」的摩擦声引出下文对父亲写毛笔字的回忆，照应标题，为下文作铺垫。效果上：以声音入笔，画面感强，引发读者的阅读兴趣。",
        ideas=[
            ("内容", "这段写了什么 + 什么氛围", "交代了……，营造了……氛围"),
            ("结构", "引出下文／铺垫／照应标题／设悬念／承上启下", "引出下文……，照应……"),
            ("效果", "对读者的作用", "引发阅读兴趣／增强画面感"),
            ("避坑", "记叙文不考「点明时间地点」", "写之前问：这句能让读者产生感觉吗"),
        ],
    ),
    dict(
        sec="wl", no="1019 第2题(2)①", kind="修辞赏析", full=3, got=None,
        img="wl1019.jpg",
        wrote="运用**夸张**，「掀起巨浪」「波澜起伏」突出看到自己的字被展示后的「巨大成就之感」。",
        miss=[
            ("手法", "❌", "**漏了「比喻」**——把内心情绪比作暖流、巨浪，是比喻 + 夸张双重手法"),
            ("情感词", "❌", "「巨大成就之感」不是标准说法，应为「激动、喜悦、自豪」"),
        ],
        answer="运用**比喻和夸张**，把内心涌动的情绪比作「暖流」「巨浪」，形象写出「我」看到自己的字被展示时内心翻涌的激动、喜悦与自豪，化抽象情感为可感画面，富有感染力。",
        ideas=[
            ("1 数手法", "一句话里可能有两三种，别只挑最显眼的", "「暖流」「巨浪」＝比喻；「掀起」＝夸张"),
            ("2 说内容", "写出了什么", "形象写出……"),
            ("3 落情感", "用标准情感词", "激动、喜悦、自豪、愧疚、怀念"),
        ],
    ),
    dict(
        sec="wl", no="1019 第2题(2)②", kind="加点词赏析", full=3, got=None,
        img="wl1019.jpg",
        wrote="「久久」形容时间长，写出父亲看了许久，体现欣赏赞美，侧面体现「我」字写得好。",
        miss=[("人物性格", "❌", "只写了行为和赞美，**没写父亲是个什么样的人**——不善言辞、沉默的爱，正是《背影》单元的核心母题")],
        answer="「久久」是「很长时间」的意思，写父亲在展示栏前长时间驻足凝视，以**细节描写**（动作、时间）表现他内心的欣慰与骄傲；父亲不善言辞，「久久」二字把他沉默而深沉的爱写得含蓄动人，也侧面烘托「我」的字确实出色。",
        ideas=[
            ("1 释词", "这个词在句中什么意思", "「久久」＝很长时间"),
            ("2 描画面", "什么动作、什么细节、什么描写", "动作描写／细节描写"),
            ("3 落人物", "写出他是个什么样的人", "**这一步你现在总是缺**"),
        ],
    ),
    dict(
        sec="wl", no="1019 第2题(3)", kind="插叙作用", full=3, got=None,
        img="wl1019.jpg",
        wrote="不多余。插叙父亲的经历，写他家境贫困仍用猪鬃毛笔写字，体现对写毛笔字的崇敬，为下文教「我」写字作铺垫，表达敬佩怀念。",
        miss=[
            ("结构术语", "❌", "写成了「讲故事」，没答「使情节连贯」「使人物形象更丰满」"),
            ("主旨", "❌", "没点「深化『传承』这一主旨」"),
        ],
        answer="不多余。此处插叙父亲少年时用猪鬃自制毛笔练字的经历：① 内容上，交代父亲热爱写字的缘由，写出他在贫困中依然坚持的执着；② 结构上，解释下文父亲教「我」写字的合理性，使情节连贯，也使人物形象更丰满；③ 主旨上，以父亲的「苦学」对照「我」的「习以为常」，深化「文化传承」这一主旨。",
        ideas=[
            ("内容", "补充了什么情节／背景", "交代了……，写出……"),
            ("结构", "铺垫／照应／使情节连贯／使形象丰满", "为下文……作铺垫"),
            ("主旨", "深化／突出什么", "深化了……的主旨"),
            ("套路", "四条里挑三条写", "交代缘由 + 铺垫下文 + 丰满形象 + 深化主旨"),
        ],
    ),
]

PATTERNS = [
    ("结构角度（线索/铺垫/照应）", 4, "≈7 分", "周测14、1015标题、1019开头、1019插叙"),
    ("情感落点（总停在「写了什么」）", 4, "≈4 分", "周测15、1015赏析、1019两处"),
    ("要点数量不够（6 分题只写 3 点）", 3, "≈5 分", "周测16、17、1015标题"),
    ("同义反复（一条意思写两遍）", 3, "≈3 分", "周测12、14、17"),
    ("手法术语（比喻/象征/化静为动）", 2, "≈3 分", "周测8、1019修辞"),
    ("把非考点当考点", 2, "≈2 分", "周测16、1019开头"),
]

PLAN = [
    ("D1", "拿卷子对照课本核默写（我不代劳）", "15 min"),
    ("D2", "文言「绝」5 义项 + 《三峡》3 个例句", "15 min"),
    ("D3", "断句 5 篇，一律先翻译后断句", "20 min"),
    ("D4", "标题作用 3 篇，每篇写满 5 个角度", "20 min"),
    ("D5", "人物形象 2 篇，按「词·据·义」写 4 点", "20 min"),
    ("D6", "小传 1 篇，按五段提纲写 600 字", "40 min"),
    ("D7", "重做周测第 8、12、16、17 题", "30 min"),
]

IMG_LABEL = {
    "zt_a.jpg": "周测 第1页（左）：选择题填涂 + 默写",
    "zt_b.jpg": "周测 第1页（右）：第 8、9、11 题",
    "zt_c.jpg": "周测 第2页（左）：第 12、14 题",
    "zt_d.jpg": "周测 第2页（右）：第 15、16、17 题",
    "wl1015.jpg": "晚练 1015：第 2 题（含老师红笔批注）",
    "wl1019.jpg": "晚练 1019：第 2、3 题",
    "wl1013.jpg": "晚练 1013：作文《同学小传》",
}

SEC_TITLE = {"zt": "周测 20261016（79/100）", "wl": "三次晚练"}

# ---------------------------------------------------------------- Markdown
def md_inline(t):
    return t

def build_md():
    L = []
    A = L.append
    A("# 语文错题诊断报告")
    A("")
    A("**2026-10-13 ～ 10-20**｜4 份卷｜**360 / 400（90.0%）**｜失分 40")
    A("")
    A("> 每题四段：你写的 → 你缺的 → **缺的那部分完整答案** → **完整答题思路**。默写不做逐空分析（识图不可靠）。")
    A("")
    A("## 成绩单")
    A("")
    A("| 日期 | 卷子 | 类型 | 得分 | 失分 |")
    A("|---|---|---|---|---|")
    for d, n, k, s, f in WEEK:
        A(f"| {d} | {n} | {k} | {s} | **{f - s}** |")
    A("")
    A("## 失分结构")
    A("")
    A("| 类型 | 失分 | 占比 |")
    A("|---|---|---|")
    for n, v, p in LOSS:
        A(f"| {n} | {v} | {p}% |")
    A("")
    A("**结论**：不是不会，是每题少答 1～2 个得分点。19 分（47.5%）属于「会做但没答全」。")
    A("")
    for sec in ("zt", "wl"):
        A(f"## {SEC_TITLE[sec]}")
        A("")
        for c in [x for x in CARDS if x["sec"] == sec]:
            got = f'{c["got"]}/{c["full"]}' if c["got"] is not None else f'—/{c["full"]}'
            A(f'### {c["no"]}　{c["kind"]}　（{got}）')
            A("")
            A(f'**你写的**：{c["wrote"]}')
            A("")
            A("**你缺的**：")
            A("")
            A("| 得分点 | 有没有 | 问题 |")
            A("|---|---|---|")
            for a, b, d in c["miss"]:
                A(f"| {a} | {b} | {d} |")
            A("")
            A("**你缺的那部分，完整答案**：")
            A("")
            for line in c["answer"].split("\n"):
                A(f"> {line}" if line.strip() else ">")
            A("")
            A("**完整答题思路**：")
            A("")
            A("| 步 | 做什么 | 句式 / 提醒 |")
            A("|---|---|---|")
            for a, b, d in c["ideas"]:
                A(f"| {a} | {b} | {d} |")
            A("")
            A(f'原卷：`assets/{c["img"]}`（{IMG_LABEL[c["img"]]}）')
            A("")
    A("## 你缺什么：6 类，重复出现")
    A("")
    A("| 缺的东西 | 次数 | 损失 | 出现在 |")
    A("|---|---|---|---|")
    for a, b, c_, d in PATTERNS:
        A(f"| {a} | {b} | {c_} | {d} |")
    A("")
    A("**一句话**：不缺知识，缺一套检查清单——写完不看角度齐不齐、有没有重复、最后一层情感写没写。")
    A("")
    A("## 7 天计划")
    A("")
    A("| | 任务 | 时间 |")
    A("|---|---|---|")
    for a, b, c_ in PLAN:
        A(f"| {a} | {b} | {c_} |")
    A("")
    A("---")
    A("")
    A("数据说明：周测来自「学情报告→答题卡」，逐题得分精确；晚练来自「作业报告→答题卡」，"
      "只按大题给分（不提供逐小题分），扣分定位为按作答对照评分标准推断。10-20 晚练无语文。")
    return "\n".join(L)


# ---------------------------------------------------------------- HTML
def esc(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"「([^」]*)」", r"<em>「\1」</em>", t)
    return t


def esc_plain(t):
    """不把「」变成 em（用于表格里的引用，避免满屏斜体）"""
    t = html.escape(t, quote=False)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)


CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#1b1916;--ink2:#4b453c;--ink3:#8a8177;
  --paper:#faf8f4;--card:#fff;--line:#e8e2d7;
  --red:#b03a2e;--blue:#2f5d8a;--amber:#9a6b1f;--green:#3f7a52;
}
body{
  background:var(--paper);color:var(--ink);line-height:1.75;
  font-family:"Source Han Serif SC","Songti SC","Noto Serif CJK SC","Microsoft YaHei",serif;
  -webkit-font-smoothing:antialiased;
}
/* 顶栏 */
.topbar{
  position:sticky;top:0;z-index:50;background:rgba(250,248,244,.94);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line);
}
.topbar-in{max-width:900px;margin:0 auto;padding:10px 24px;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.brand{font-size:13px;font-weight:700;letter-spacing:.14em;color:var(--red);white-space:nowrap}
.nav{display:flex;gap:6px;flex-wrap:wrap;flex:1}
.nav a{
  font-size:12.5px;color:var(--ink2);text-decoration:none;padding:4px 10px;border-radius:20px;
  border:1px solid var(--line);background:#fff;font-family:system-ui,sans-serif;white-space:nowrap;
  transition:.15s;
}
.nav a:hover{background:var(--red);color:#fff;border-color:var(--red)}
.print-btn{
  font-size:12.5px;padding:5px 12px;border-radius:6px;border:1px solid var(--line);background:#fff;
  cursor:pointer;font-family:system-ui,sans-serif;color:var(--ink2);
}
.print-btn:hover{border-color:var(--ink3)}

.wrap{max-width:900px;margin:0 auto;padding:34px 24px 80px}
h1{font-size:30px;letter-spacing:.01em;margin-bottom:10px}
.sub{font-size:13.5px;color:var(--ink3);font-family:system-ui,sans-serif;display:flex;gap:16px;flex-wrap:wrap}
.sub b{color:var(--ink2)}
h2{font-size:20px;margin:38px 0 14px;padding-left:12px;border-left:4px solid var(--red)}
h2 .cnt{font-size:12.5px;color:var(--ink3);font-weight:400;margin-left:8px;font-family:system-ui,sans-serif}

/* 概览卡 */
.overview{display:grid;grid-template-columns:1.15fr 1fr;gap:14px;margin-top:22px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.panel h3{font-size:13px;color:var(--ink3);font-weight:600;letter-spacing:.06em;margin-bottom:12px;font-family:system-ui,sans-serif}
.bar-row{display:grid;grid-template-columns:96px 1fr 44px;align-items:center;gap:10px;margin:9px 0;font-size:13px}
.bar-row .nm{font-family:system-ui,sans-serif;color:var(--ink2);white-space:nowrap}
.bar{height:7px;background:#efe9df;border-radius:4px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:4px;background:var(--red)}
.bar-row .vv{text-align:right;font-family:system-ui,sans-serif;font-weight:700;font-size:13px;color:var(--red)}
.week-row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px dashed #f0ebe2;font-size:13.5px}
.week-row:last-child{border:0}
.week-row .d{color:var(--ink3);font-family:system-ui,sans-serif;font-size:12.5px;width:52px}
.week-row .n{flex:1;margin:0 10px}
.week-row .s{font-family:system-ui,sans-serif;font-weight:700;font-size:15px}
.week-row .s small{color:var(--ink3);font-weight:400;font-size:11.5px}

/* 题卡 */
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:14px 0;overflow:hidden;scroll-margin-top:64px}
.card-hd{display:flex;align-items:center;gap:10px;padding:13px 18px;border-bottom:1px solid #f3eee5;flex-wrap:wrap}
.card-hd .no{font-size:16px;font-weight:700}
.card-hd .kind{font-size:12.5px;color:var(--ink3);font-family:system-ui,sans-serif;background:#f6f2ea;padding:2px 8px;border-radius:4px}
.card-hd .sp{margin-left:auto;display:flex;align-items:center;gap:10px;font-family:system-ui,sans-serif}
.score{font-size:13px;font-weight:700}
.score .lose{color:var(--red)}
.score .ok{color:var(--green)}
.mini-bar{width:70px;height:5px;background:#efe9df;border-radius:3px;overflow:hidden}
.mini-bar i{display:block;height:100%;background:var(--red)}
.img-btn{
  font-size:12px;padding:4px 10px;border-radius:6px;border:1px solid var(--line);background:#fff;
  cursor:pointer;color:var(--blue);font-family:system-ui,sans-serif;
}
.img-btn:hover{background:var(--blue);color:#fff;border-color:var(--blue)}
.card-bd{padding:14px 18px 18px}
.lbl{font-size:11.5px;letter-spacing:.1em;color:var(--ink3);font-family:system-ui,sans-serif;margin:14px 0 7px}
.lbl:first-child{margin-top:0}
.wrote{font-size:14px;color:var(--ink2);background:#faf7f1;border-left:3px solid #e2d9c8;padding:9px 12px;border-radius:0 6px 6px 0}

.subnav{
  position:sticky;top:50px;z-index:40;display:flex;gap:6px;flex-wrap:wrap;
  padding:8px 0 10px;margin:-6px 0 6px;
  background:linear-gradient(var(--paper) 72%,rgba(250,248,244,0));
}
.subnav a{
  font-size:12px;padding:3px 10px;border-radius:14px;border:1px solid var(--line);
  background:#fff;color:var(--ink2);text-decoration:none;font-family:system-ui,sans-serif;white-space:nowrap;
}
.subnav a:hover{background:var(--blue);color:#fff;border-color:var(--blue)}

table{width:100%;border-collapse:collapse;font-size:14px;font-family:system-ui,"Microsoft YaHei",sans-serif}
th{text-align:left;font-weight:600;color:var(--ink3);font-size:12px;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid #f4efe7;vertical-align:top}
tr:last-child td{border-bottom:0}
td.st{width:58px;text-align:center;font-size:14px}
td.st.no{color:var(--red);font-weight:700}
td.st.half{color:var(--amber)}
td.st.yes{color:var(--green)}
td b{color:#000}

details{border:1px solid #eadfcc;border-radius:8px;margin:10px 0;background:#fffdf8}
details[open]{background:#fffdf8}
summary{
  cursor:pointer;padding:10px 14px;font-size:13.5px;font-weight:700;color:var(--amber);
  list-style:none;display:flex;align-items:center;gap:8px;font-family:system-ui,sans-serif;
}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";font-size:11px;transition:.2s;color:var(--amber)}
details[open] summary::before{transform:rotate(90deg)}
summary:hover{background:#fdf7e8}
.dt-bd{padding:2px 16px 14px;font-size:14px;color:#4a3f2a}
.dt-bd p{margin:8px 0}
.dt-bd table{font-size:13px}
.dt-bd th{color:#9a8b6a;border-color:#efe6d2}
.dt-bd td{border-color:#f5eeda}
.dt-bd em{font-style:normal;color:#8a5a1a;background:#fbf1dc;padding:0 3px;border-radius:3px}

.pat td b{color:var(--red)}
.plan td:first-child{color:var(--red);font-weight:700;width:46px}

.note{font-size:12.5px;color:var(--ink3);margin-top:26px;padding-top:14px;border-top:1px solid var(--line);line-height:1.7;font-family:system-ui,sans-serif}

/* 图片弹层 */
.overlay{
  position:fixed;inset:0;background:rgba(20,18,15,.86);z-index:100;display:none;
  padding:24px;overflow:auto;
}
.overlay.on{display:block}
.overlay img{max-width:100%;display:block;margin:0 auto;border-radius:6px;box-shadow:0 10px 40px rgba(0,0,0,.5)}
.overlay .cap{color:#e8e2d7;text-align:center;font-size:13px;margin-bottom:12px;font-family:system-ui,sans-serif}
.overlay .x{
  position:fixed;top:16px;right:20px;width:38px;height:38px;border-radius:50%;border:0;
  background:rgba(255,255,255,.14);color:#fff;font-size:20px;cursor:pointer;line-height:1;
}
.overlay .x:hover{background:rgba(255,255,255,.28)}

@media (max-width:760px){
  .overview{grid-template-columns:1fr}
  .wrap{padding:24px 14px 60px}
  h1{font-size:23px}
  .card-hd .sp{margin-left:0;width:100%;justify-content:flex-start}
  .bar-row{grid-template-columns:78px 1fr 40px}
}
@media print{
  .topbar,.img-btn,.print-btn,.overlay{display:none!important}
  body{background:#fff}
  .card{break-inside:avoid;border-color:#ddd}
  details{border-color:#ddd}
  details:not([open]) .dt-bd{display:block}
  h2{break-after:avoid}
}
"""

JS = r"""
document.querySelectorAll('.img-btn').forEach(b=>{
  b.addEventListener('click',()=>{
    const o=document.getElementById('ov');
    o.querySelector('img').src=b.dataset.img;
    o.querySelector('.cap').textContent=b.dataset.cap;
    o.classList.add('on');
    document.body.style.overflow='hidden';
  });
});
const ov=document.getElementById('ov');
function closeOv(){ov.classList.remove('on');document.body.style.overflow='';}
ov.addEventListener('click',e=>{if(e.target===ov||e.target.classList.contains('x'))closeOv();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeOv();});
document.getElementById('pb').addEventListener('click',()=>{
  document.querySelectorAll('details').forEach(d=>d.open=true);
  window.print();
});
const tg=document.getElementById('tg');
tg.addEventListener('click',()=>{
  const all=[...document.querySelectorAll('details')];
  const open=all.every(d=>d.open);
  all.forEach(d=>d.open=!open);
  tg.textContent=open?'展开全部':'收起全部';
});
"""


def st_cls(v):
    return {"❌": "no", "半": "half", "✅": "yes"}.get(v, "")


def build_html():
    for i, c in enumerate(CARDS):
        c["_id"] = f"q{i}"
    total = sum(s for _, _, _, s, _ in WEEK)
    full = sum(f for _, _, _, _, f in WEEK)
    h = []
    A = h.append
    A('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<title>语文错题诊断 · 2026.10.13–10.20</title>')
    A(f"<style>{CSS}</style></head><body>")

    # 顶栏
    A('<div class="topbar"><div class="topbar-in">')
    A('<span class="brand">语文错题诊断</span>')
    A('<nav class="nav">')
    A('<a href="#overview">概览</a>')
    for sec in ("zt", "wl"):
        A(f'<a href="#{sec}">{SEC_TITLE[sec].split("（")[0]}</a>')
    A('<a href="#patterns">缺什么</a><a href="#plan">计划</a>')
    A('</nav>')
    A('<button class="print-btn" id="tg">展开全部</button>')
    A('<button class="print-btn" id="pb">打印 / 存 PDF</button>')
    A("</div></div>")

    A('<div class="wrap">')
    A("<h1>最近一周语文错题诊断</h1>")
    A('<div class="sub"><span><b>周期</b> 2026-10-13 → 10-20</span>'
      f'<span><b>得分</b> {total} / {full}（{total/full*100:.1f}%）</span>'
      f'<span><b>失分</b> {full-total}</span></div>')

    # 概览
    A('<div class="overview" id="overview">')
    A('<div class="panel"><h3>四场卷子</h3>')
    for d, n, k, s, f in WEEK:
        A(f'<div class="week-row"><span class="d">{d}</span><span class="n">{n}</span>'
          f'<span class="s">{s}<small>/{f}</small></span></div>')
    A("</div>")
    A('<div class="panel"><h3>失分结构（共 40 分）</h3>')
    for n, v, p in LOSS:
        A(f'<div class="bar-row"><span class="nm">{n}</span>'
          f'<span class="bar"><i style="width:{p*2}%"></i></span>'
          f'<span class="vv">{v}</span></div>')
    A("</div></div>")

    # 题卡
    for sec in ("zt", "wl"):
        cards = [x for x in CARDS if x["sec"] == sec]
        A(f'<h2 id="{sec}">{SEC_TITLE[sec]}</h2>')
        A('<div class="subnav">')
        for c in cards:
            A(f'<a href="#{c["_id"]}">{c["no"].replace(" ", "")}</a>')
        A("</div>")
        for c in cards:
            got = c["got"]
            if got is None:
                sc = f'<span class="score">— / {c["full"]}</span>'
                pct = 0
            else:
                lose = c["full"] - got
                cls = "lose" if lose > 0 else "ok"
                sc = (f'<span class="score"><span class="{cls}">{got}</span>'
                      f' / {c["full"]}</span>')
                pct = got / c["full"] * 100
            A(f'<article class="card" id="{c["_id"]}">')
            A('<div class="card-hd">')
            A(f'<span class="no">{c["no"]}</span><span class="kind">{c["kind"]}</span>')
            A('<span class="sp">')
            A(f'<span class="mini-bar"><i style="width:{pct:.0f}%"></i></span>')
            A(sc)
            A(f'<button class="img-btn" data-img="assets/{c["img"]}" '
              f'data-cap="{esc_plain(IMG_LABEL[c["img"]])}">看原卷</button>')
            A("</span></div>")
            A('<div class="card-bd">')
            A('<div class="lbl">你写的</div>')
            A(f'<div class="wrote">{esc_plain(c["wrote"])}</div>')

            A('<div class="lbl">你缺的</div>')
            A("<table><thead><tr><th>得分点</th><th>有没有</th><th>问题</th></tr></thead><tbody>")
            for a, b, d in c["miss"]:
                A(f'<tr><td>{esc_plain(a)}</td><td class="st {st_cls(b)}">{b}</td>'
                  f"<td>{esc(d)}</td></tr>")
            A("</tbody></table>")

            A('<details><summary>你缺的那部分，完整答案（点开）</summary><div class="dt-bd">')
            for line in c["answer"].split("\n"):
                if line.strip():
                    A(f"<p>{esc(line)}</p>")
            A("</div></details>")

            A('<details><summary>完整答题思路（同类题照走）</summary><div class="dt-bd">')
            A("<table><thead><tr><th>步</th><th>做什么</th><th>句式 / 提醒</th></tr></thead><tbody>")
            for a, b, d in c["ideas"]:
                A(f"<tr><td><b>{esc_plain(a)}</b></td><td>{esc_plain(b)}</td>"
                  f"<td>{esc(d)}</td></tr>")
            A("</tbody></table></div></details>")
            A("</div></article>")

    # 模式
    A('<h2 id="patterns">你缺什么：6 类，重复出现</h2>')
    A('<table class="pat"><thead><tr><th>缺的东西</th><th>次数</th><th>损失</th>'
      "<th>出现在</th></tr></thead><tbody>")
    for a, b, c_, d in PATTERNS:
        A(f"<tr><td><b>{esc_plain(a)}</b></td><td>{b}</td><td>{c_}</td>"
          f"<td style='color:#8a8177'>{esc_plain(d)}</td></tr>")
    A("</tbody></table>")
    A('<p style="margin-top:12px;font-size:14px;color:#4b453c">'
      "不缺知识，缺一套<b>检查清单</b>——写完不看角度齐不齐、有没有重复、最后一层情感写没写。</p>")

    # 计划
    A('<h2 id="plan">7 天计划</h2>')
    A('<table class="plan"><thead><tr><th></th><th>任务</th><th>时间</th></tr></thead><tbody>')
    for a, b, c_ in PLAN:
        A(f"<tr><td>{a}</td><td>{esc_plain(b)}</td><td>{c_}</td></tr>")
    A("</tbody></table>")

    A('<div class="note">周测数据来自「学情报告→答题卡」，逐题得分精确；晚练来自「作业报告→答题卡」，'
      "只按大题给分（不提供逐小题分），扣分定位为按作答对照评分标准推断。"
      "默写不做逐空分析——手写扫描件识图不可靠。10-20 晚练无语文。</div>")
    A("</div>")

    A('<div class="overlay" id="ov"><button class="x">×</button>'
      '<div class="cap"></div><img alt="原卷"></div>')
    A(f"<script>{JS}</script></body></html>")
    return "\n".join(h)


def main():
    ASSETS.mkdir(exist_ok=True)
    md = build_md()
    (OUT_DIR / "语文错题分析_20261013-1020.md").write_text(md, encoding="utf-8")
    (OUT_DIR / "语文错题分析_20261013-1020.html").write_text(build_html(), encoding="utf-8")
    print("md/html ok", len(md))


if __name__ == "__main__":
    main()
