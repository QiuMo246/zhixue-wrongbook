import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';

// 荧光笔高亮：一个从左到右扫过的黄色块（官网 .hl 的 100deg 渐变质感）
export const Highlight: React.FC<{
  delay: number;
  duration?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}> = ({ delay, duration = 28, children, style }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [delay, delay + duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <span style={{ position: 'relative', display: 'inline-block', ...style }}>
      <span
        style={{
          position: 'absolute',
          left: '-0.06em',
          right: '-0.06em',
          top: '12%',
          bottom: '10%',
          background: `linear-gradient(100deg, transparent 2%, ${COLORS.yellow} 6%, ${COLORS.yellow} 94%, transparent 98%)`,
          transform: `scaleX(${p})`,
          transformOrigin: 'left center',
          zIndex: 0,
        }}
      />
      <span style={{ position: 'relative', zIndex: 1 }}>{children}</span>
    </span>
  );
};

// 分镜2：主标题「把智学网的错题，变成你的专属练习卷」+ 荧光笔划重点
export const Scene2Title: React.FC = () => {
  const frame = useCurrentFrame();

  const line1 = interpolate(frame, [5, 30], [0, 1], { extrapolateRight: 'clamp' });
  const line2 = interpolate(frame, [18, 45], [0, 1], { extrapolateRight: 'clamp' });
  const sub = interpolate(frame, [70, 95], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontFamily: FONT_HEAD,
            fontWeight: 900,
            fontSize: 92,
            lineHeight: 1.3,
            color: COLORS.ink,
            opacity: line1,
            transform: `translateY(${interpolate(line1, [0, 1], [24, 0])}px)`,
          }}
        >
          把智学网的错题，
        </div>
        <div
          style={{
            fontFamily: FONT_HEAD,
            fontWeight: 900,
            fontSize: 92,
            lineHeight: 1.3,
            color: COLORS.ink,
            opacity: line2,
            transform: `translateY(${interpolate(line2, [0, 1], [24, 0])}px)`,
          }}
        >
          变成你的
          <Highlight delay={40} duration={26} style={{ padding: '0 0.08em' }}>
            专属练习卷
          </Highlight>
        </div>
        <div
          style={{
            marginTop: 46,
            fontFamily: FONT_BODY,
            fontSize: 36,
            color: COLORS.inkSoft,
            maxWidth: 1240,
            margin: '46px auto 0',
            lineHeight: 1.7,
            opacity: sub,
            transform: `translateY(${interpolate(sub, [0, 1], [16, 0])}px)`,
          }}
        >
          同步错题、分析错因、出同类题、自动批改 —— 数据全在你自己电脑上
        </div>
      </div>
    </AbsoluteFill>
  );
};
