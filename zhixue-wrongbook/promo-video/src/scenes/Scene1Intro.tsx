import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';
import { PaperCard } from '../components/PaperCard';
import { Stamp } from '../components/Stamp';

// 分镜1：错题卡拍落 + 大红 × 盖章 + kicker「给初中生的错题本外挂」
export const Scene1Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const kicker = spring({ frame: frame - 95, fps, config: { damping: 13 } });
  const kickerChars = '给初中生的错题本外挂'.split('').map((ch, i) => {
    const p = spring({ frame: frame - 95 - i * 2, fps, config: { damping: 12 } });
    return (
      <span
        key={i}
        style={{
          display: 'inline-block',
          opacity: p,
          transform: `translateY(${interpolate(p, [0, 1], [14, 0])}px)`,
        }}
      >
        {ch}
      </span>
    );
  });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      {/* 背后一个大淡红 × */}
      <div
        style={{
          position: 'absolute',
          fontFamily: FONT_HEAD,
          fontWeight: 900,
          fontSize: 560,
          color: 'rgba(224, 69, 58, 0.08)',
          transform: `rotate(-10deg) translateY(${interpolate(frame, [0, 180], [20, -10])}px)`,
        }}
      >
        ×
      </div>

      <PaperCard delay={10} tilt={-1.6} style={{ width: 720, textAlign: 'left', position: 'relative' }}>
        <div style={{ color: COLORS.inkSoft, fontSize: 30, marginBottom: 14 }}>物理 · 午练 · 第 9 题</div>
        <div style={{ fontFamily: FONT_HEAD, fontWeight: 900, fontSize: 46, marginBottom: 18 }}>
          得 <span style={{ color: COLORS.red, fontSize: 62 }}>0</span> / 3 分
        </div>
        <div
          style={{
            fontSize: 32,
            color: COLORS.inkSoft,
            textDecoration: 'line-through',
            textDecorationColor: COLORS.red,
            textDecorationThickness: 2.5,
          }}
        >
          解：由 F=ρgh 可知物体所受浮力为……
        </div>

        <div style={{ position: 'absolute', right: -70, top: -60 }}>
          <Stamp delay={55} symbol="×" size={200} rotate={-6} />
        </div>
      </PaperCard>

      <div
        style={{
          marginTop: 64,
          fontFamily: FONT_HEAD,
          fontWeight: 900,
          fontSize: 56,
          color: COLORS.ink,
          letterSpacing: '0.05em',
          opacity: kicker,
        }}
      >
        {kickerChars}
      </div>
    </AbsoluteFill>
  );
};
