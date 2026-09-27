import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';
import { DialogueBubble } from '../components/DialogueBubble';
import { Highlight } from './Scene2Title';

// 分镜5 对话③：出练习卷 —— 薄弱知识点荧光黄划过，题目逐条落位
export const Scene5Paper: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const questions = [
    '1. 一艘轮船从长江驶入东海，浮力如何变化？',
    '2. 串联电路中，两个灯泡的电流有什么关系？',
    '3. 汽水罐上的吸盘为什么能吸在墙上？',
  ];

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 1240, display: 'flex', flexDirection: 'column', gap: 26 }}>
        <DialogueBubble side="user" text="给我出一份同类题练习卷" delay={6} width={640} />

        <div
          style={{
            background: COLORS.card,
            border: `2.5px solid ${COLORS.ink}`,
            borderRadius: 16,
            boxShadow: '6px 6px 0 rgba(30,42,68,0.16)',
            padding: '36px 52px',
            opacity: interpolate(frame, [50, 72], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            }),
            transform: `rotate(-0.4deg) translateY(${interpolate(frame, [50, 72], [40, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })}px)`,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 24 }}>
            <span
              style={{
                fontFamily: FONT_HEAD,
                fontWeight: 900,
                fontSize: 42,
                borderBottom: `4px solid ${COLORS.red}`,
                paddingBottom: 4,
              }}
            >
              专属练习卷 · 物理
            </span>
            <span style={{ fontSize: 30, color: COLORS.inkSoft }}>
              针对：
              <Highlight delay={86} duration={22} style={{ fontSize: 30 }}>
                浮力 · 电路 · 压强
              </Highlight>
            </span>
          </div>

          {questions.map((q, i) => {
            const p = spring({ frame: frame - 100 - i * 18, fps, config: { damping: 15 } });
            return (
              <div
                key={i}
                style={{
                  fontFamily: FONT_BODY,
                  fontSize: 34,
                  lineHeight: 1.9,
                  opacity: p,
                  transform: `translateX(${interpolate(p, [0, 1], [-30, 0])}px)`,
                }}
              >
                {q}
              </div>
            );
          })}
        </div>

        <div
          style={{
            fontFamily: FONT_BODY,
            fontSize: 32,
            color: COLORS.inkSoft,
            textAlign: 'center',
            opacity: interpolate(frame, [165, 190], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            }),
          }}
        >
          只从 341 个受控知识点里选题，选不了就不硬选
        </div>
      </div>
    </AbsoluteFill>
  );
};
