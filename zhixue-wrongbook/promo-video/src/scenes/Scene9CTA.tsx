import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD, FONT_MONO, SHADOW_HARD } from '../theme';
import { Highlight } from './Scene2Title';

// 分镜9：结尾 CTA —— 复制安装提示词，AI 自己装
export const Scene9CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const title = spring({ frame: frame - 5, fps, config: { damping: 14 } });
  const btn = spring({ frame: frame - 40, fps, config: { damping: 11, mass: 0.8 } });
  const url = interpolate(frame, [75, 100], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontFamily: FONT_HEAD,
            fontWeight: 900,
            fontSize: 78,
            color: COLORS.ink,
            opacity: title,
            transform: `translateY(${interpolate(title, [0, 1], [26, 0])}px)`,
          }}
        >
          把错题变成你的
          <Highlight delay={18} duration={24} style={{ padding: '0 0.1em' }}>
            专属练习卷
          </Highlight>
        </div>

        <div
          style={{
            marginTop: 70,
            display: 'flex',
            justifyContent: 'center',
            transform: `translateY(${interpolate(btn, [0, 1], [80, 0])}px) scale(${interpolate(btn, [0, 1], [0.92, 1])})`,
            opacity: btn,
          }}
        >
          <div
            style={{
              background: COLORS.red,
              color: '#fff',
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: 52,
              borderRadius: 14,
              padding: '28px 72px',
              border: `2.5px solid ${COLORS.ink}`,
              boxShadow: SHADOW_HARD,
              transform: 'rotate(-0.6deg)',
              letterSpacing: '0.04em',
            }}
          >
            复制安装提示词，AI 自己装
          </div>
        </div>

        <div
          style={{
            marginTop: 58,
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'center',
            gap: 18,
            opacity: url,
          }}
        >
          <span
            style={{
              fontFamily: FONT_BODY,
              fontSize: 30,
              color: COLORS.inkSoft,
              border: `2px solid ${COLORS.ink}`,
              borderRadius: 999,
              padding: '2px 20px',
              background: COLORS.yellow,
            }}
          >
            官网
          </span>
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: 42,
              fontWeight: 700,
              color: COLORS.blue,
              textDecoration: 'underline',
              textDecorationThickness: 2.5,
              textUnderlineOffset: 6,
            }}
          >
            https://qiumo-zxw.pages.dev/
          </span>
        </div>
        <div
          style={{
            marginTop: 20,
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'center',
            gap: 18,
            opacity: interpolate(frame, [90, 112], [0, 1], { extrapolateRight: 'clamp' }),
          }}
        >
          <span
            style={{
              fontFamily: FONT_BODY,
              fontSize: 30,
              color: COLORS.inkSoft,
              border: `2px solid ${COLORS.ink}`,
              borderRadius: 999,
              padding: '2px 20px',
              background: COLORS.card,
            }}
          >
            仓库
          </span>
          <span style={{ fontFamily: FONT_MONO, fontSize: 34, color: COLORS.ink }}>
            gitee.com/qiu_moRs/zhixue-wrongbook
          </span>
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: 30,
            fontFamily: FONT_BODY,
            color: COLORS.inkSoft,
            opacity: url,
          }}
        >
          智学网错题助手 · 给初中生的错题本外挂
        </div>
      </div>
    </AbsoluteFill>
  );
};

