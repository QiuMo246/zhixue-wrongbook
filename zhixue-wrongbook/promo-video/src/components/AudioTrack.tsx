import React from 'react';
import { Audio, Sequence, staticFile } from 'remotion';
import { SCENES } from '../theme';

// 音量总闸：用户要求「保守」
const MASTER = 0.55;

type Cue = {
  /** 音效名（public/sfx/<name>.wav） */
  sfx: string;
  /** 绝对帧号（30fps，跨全片） */
  at: number;
  /** 相对音量倍率 */
  gain?: number;
};

const c = (sfx: string, at: number, gain = 1): Cue => ({ sfx, at, gain });

// 分配原则：按「元素类型」给不同音色，而不是所有弹入都用同一个 pop。
//   纸片卡  → card_drop / paper_flip（低闷、纸张摩擦）
//   徽章章  → stamp / chip（印章冲击 vs 高频贴纸）
//   荧光笔  → highlighter / pencil（笔尖摩擦）
//   芯片数据→ chip / blip0-5（递增音高，像程序在推进）
//   金属转场→ metal_click（带泛音，明显不同于纸质）
//   成功确认→ success / bell
const blips = ['blip0', 'blip1', 'blip2', 'blip3', 'blip4', 'blip5'];

// 帧号 = SCENES.<场景>.from + 该场景内的局部帧（从各 Scene*.tsx 的 delay/spring 反推）
export const CUES: Cue[] = [
  // 分镜0 开场钩子 0–270：智学网错题 → 拿到手
  c('card_drop', SCENES.hook.from + 22),        // 左卡「智学网·上次考试」弹入
  c('card_drop', SCENES.hook.from + 52, 0.9),   // 右卡「我的错题本·本机」
  c('whoosh_soft', SCENES.hook.from + 80, 0.8), // 大红箭头出现
  c('snap', SCENES.hook.from + 92),             // 错题小卡被「吸」过去
  c('snap', SCENES.hook.from + 108, 0.85),
  c('snap', SCENES.hook.from + 124, 0.85),
  c('chime_up', SCENES.hook.from + 150, 0.7),  // 计数蹦到 12 道
  c('stamp', SCENES.hook.from + 162),           // 红圈 ✓ 章盖下

  // 分镜1 错题卡 270–450
  c('card_drop', SCENES.intro.from + 10),       // 错题卡拍落
  c('stamp', SCENES.intro.from + 55),           // 大红 × 盖章
  c('pencil', SCENES.intro.from + 95, 0.55),    // kicker 像被写下

  // 分镜2 主标题 450–630
  c('metal_click', SCENES.title.from + 5, 0.7), // 标题第一行（金属转轴质感）
  c('highlighter', SCENES.title.from + 40),     // 荧光笔划过「专属练习卷」

  // 分镜3 同步错题 630–840
  c('pencil', SCENES.sync.from + 8, 0.5),       // 聊天气泡「写」出来
  c('chip', SCENES.sync.from + 60),             // 通道一（芯片落位）
  c('chip', SCENES.sync.from + 76, 0.95),
  c('chip', SCENES.sync.from + 92, 0.9),        // 通道三
  c('success', SCENES.sync.from + 130, 0.8),     // 「同步完成 ✓」

  // 分镜4 薄弱项诊断 840–1080
  c('pencil', SCENES.diagnose.from + 6, 0.5),
  c('stamp', SCENES.diagnose.from + 48, 0.75),   // 诊断闸门红框卡落下
  c('blip1', SCENES.diagnose.from + 78, 0.7),   // 「哪个科目？」
  c('blip3', SCENES.diagnose.from + 88, 0.7),   // 「哪些考试？」
  c('pencil', SCENES.diagnose.from + 118, 0.5),
  // 薄弱项进度条逐条填充 → 音高递增，像数据在涨
  c(blips[0], SCENES.diagnose.from + 160, 0.55),
  c(blips[2], SCENES.diagnose.from + 166, 0.55),
  c(blips[3], SCENES.diagnose.from + 172, 0.55),
  c(blips[5], SCENES.diagnose.from + 178, 0.55),

  // 分镜5 出练习卷 1080–1320
  c('pencil', SCENES.paper.from + 6, 0.5),
  c('page_turn', SCENES.paper.from + 50, 0.8),   // 练习卷卡片展开
  c('highlighter', SCENES.paper.from + 86, 0.85),// 荧光黄划过薄弱知识点
  c('paper_flip', SCENES.paper.from + 100, 0.7), // 题目逐条落位
  c('paper_flip', SCENES.paper.from + 118, 0.68),
  c('paper_flip', SCENES.paper.from + 136, 0.66),

  // 分镜6 自动批改 1320–1530
  c('pencil', SCENES.grade.from + 8, 0.5),
  c('card_drop', SCENES.grade.from + 52, 0.85),  // 批改结果卡
  c('stamp', SCENES.grade.from + 95),            // 红笔大 ✓ 盖章
  c('success', SCENES.grade.from + 120, 0.85),   // 「10 / 10 分」

  // 分镜7 数字快闪 1530–1740：四张卡连拍，用音高递增制造「越拍越快」
  c('card_drop', SCENES.numbers.from + 30),       // 27 个工具
  c('chip', SCENES.numbers.from + 44, 0.9),       // 8 类错因
  c('card_drop', SCENES.numbers.from + 58, 0.85),// 341 知识点
  c('chip', SCENES.numbers.from + 72, 0.8),       // 332 项检查

  // 分镜8 隐私 1740–1890
  c('metal_click', SCENES.privacy.from + 8, 0.8), // 笔记本「上锁」的开合感
  c('pop_low', SCENES.privacy.from + 48, 0.85),   // 三枚徽章
  c('pop_low', SCENES.privacy.from + 58, 0.85),
  c('pop_low', SCENES.privacy.from + 68, 0.85),

  // 分镜9 CTA 1890–2070
  c('metal_click', SCENES.cta.from + 5, 0.7),    // 标题
  c('card_drop', SCENES.cta.from + 40),          // 红色按钮拍落
  c('blip4', SCENES.cta.from + 75, 0.6),         // 官网地址淡入
  c('blip2', SCENES.cta.from + 90, 0.55),        // 仓库地址

  // 分镜10 片尾署名 2070–2190
  c('whoosh', SCENES.end.from),                  // 头像自下升起
  c('blip0', SCENES.end.from + 10, 0.6),         // QiuMo 逐字（音高略上行）
  c('blip1', SCENES.end.from + 16, 0.6),
  c('blip2', SCENES.end.from + 22, 0.6),
  c('blip3', SCENES.end.from + 28, 0.6),
  c('blip4', SCENES.end.from + 34, 0.6),
  c('bell', SCENES.end.from + 58, 0.5),          // 落定：一声铃
].sort((a, b) => a.at - b.at);

// 音轨：每个音效用 Sequence 定位到绝对帧号
// 注意：Audio 自身没有「起始帧」属性，必须靠外层 Sequence from 定位；
// startFrom 是裁剪音频源用的，不要混用
export const AudioTrack: React.FC = () => (
  <>
    {CUES.map((cue, i) => (
      <Sequence key={i} from={cue.at} name={`sfx:${cue.sfx}`}>
        <Audio src={staticFile(`sfx/${cue.sfx}.wav`)} volume={MASTER * (cue.gain ?? 1)} />
      </Sequence>
    ))}
  </>
);