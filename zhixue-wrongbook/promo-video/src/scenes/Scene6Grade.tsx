import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';
import { DialogueBubble } from '../components/DialogueBubble';
import { Stamp } from '../components/Stamp';

// 分镜6 对话④：自动批改 —— 红笔大 ✓ 盖章 + 答案回代验算
export const Scene6Grade: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const chip = spring({ frame: frame - 120, fps, config: { damping: 13 } });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 1160, display: 'flex', flexDirection: 'column', gap: 26 }}>
        <DialogueBubble side="user" text="做完了，帮我批改" delay={8} width={540} />

        <div
          style={{
            background: COLORS.card,
            border: `2.5px solid ${COLORS.ink}`,
            borderRadius: 16,
            boxShadow: '6px 6px 0 rgba(30,42,68,0.16)',
            padding: '40px 56px',
            position: 'relative',
            transform: 'rotate(0.5deg)',
            opacity: interpolate(frame, [52, 74], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            }),
          }}
        >
          <div style={{ fontFamily: FONT_HEAD, fontWeight: 900, fontSize: 40, marginBottom: 16 }}>
            批改结果
          </div>
          <div style={{ fontSize: 32, color: COLORS.inkSoft, lineHeight: 1.8 }}>
            第 1 题 ✓ 回代验算通过
            <br />
            第 2 题 ✓ 单位换算正确
            <br />
            第 3 题 ✓ 公式选用正确
          </div>

          <div style={{ position: 'absolute', right: -16, top: -36 }}>
            <Stamp delay={95} symbol="✓" size={210} rotate={-8} />
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            transform: `scale(${interpolate(chip, [0, 1], [0.8, 1])})`,
            opacity: interpolate(chip, [0, 1], [0, 1]),
          }}
        >
          <div
            style={{
              background: COLORS.red,
              color: '#fff',
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: 46,
              borderRadius: 12,
              padding: '16px 48px',
              boxShadow: '6px 6px 0 rgba(30,42,68,0.9)',
              transform: 'rotate(-1deg)',
            }}
          >
            练习卷 10 / 10 分
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
