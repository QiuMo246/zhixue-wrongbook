import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD, SHADOW_CARD } from '../theme';
import { Highlight } from './Scene2Title';
import { Stamp } from '../components/Stamp';

// 开场钩子：重点强调「能获取智学网错题」—— 智学网试卷卡上的错题飞进本机错题本
export const Scene0Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const popA = spring({ frame: frame - 22, fps, config: { damping: 14 } });
  const popB = spring({ frame: frame - 52, fps, config: { damping: 14 } });
  const arrow = spring({ frame: frame - 80, fps, config: { damping: 12 } });
  const count = Math.round(
    interpolate(frame, [92, 150], [0, 12], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  );

  const title = interpolate(frame, [5, 28], [0, 1], { extrapolateRight: 'clamp' });

  const wrongRows = ['第 9 题 · 得 0/3 分', '第 14 题 · 得 1/4 分', '第 21 题 · 得 0/2 分'];

  // 三道错题从左卡飞往右卡
  const flyers = [0, 1, 2].map((i) => {
    const p = interpolate(frame, [92 + i * 16, 122 + i * 16], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return { p, i };
  });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      {/* 主标题 */}
      <div
        style={{
          fontFamily: FONT_HEAD,
          fontWeight: 900,
          fontSize: 88,
          color: COLORS.ink,
          textAlign: 'center',
          marginBottom: 74,
          opacity: title,
          transform: `translateY(${interpolate(title, [0, 1], [26, 0])}px)`,
        }}
      >
        智学网的错题，
        <Highlight delay={22} duration={26} style={{ padding: '0 0.08em' }}>
          帮你全部拿到手
        </Highlight>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 60 }}>
        {/* 左：智学网试卷卡 */}
        <div
          style={{
            width: 480,
            background: COLORS.card,
            border: `2.5px solid ${COLORS.ink}`,
            borderRadius: 16,
            boxShadow: SHADOW_CARD,
            overflow: 'hidden',
            transform: `translateY(${interpolate(popA, [0, 1], [50, 0])}px) rotate(-2deg) scale(${interpolate(popA, [0, 1], [0.94, 1])})`,
            opacity: popA,
          }}
        >
          <div
            style={{
              background: COLORS.ink,
              color: '#fff',
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: 32,
              padding: '16px 28px',
            }}
          >
            智学网 · 上次考试
          </div>
          <div style={{ padding: '22px 28px' }}>
            {wrongRows.map((r) => (
              <div
                key={r}
                style={{
                  fontFamily: FONT_BODY,
                  fontSize: 30,
                  color: COLORS.ink,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  lineHeight: 2.1,
                }}
              >
                <span style={{ color: COLORS.red, fontFamily: FONT_HEAD, fontWeight: 900 }}>×</span>
                {r}
              </div>
            ))}
          </div>
        </div>

        {/* 中：大红箭头 */}
        <div
          style={{
            fontFamily: FONT_HEAD,
            fontWeight: 900,
            fontSize: 110,
            color: COLORS.red,
            transform: `scale(${interpolate(arrow, [0, 1], [0.4, 1])}) rotate(-4deg)`,
            opacity: arrow,
          }}
        >
          →
        </div>

        {/* 右：本机错题本 */}
        <div
          style={{
            width: 480,
            background: COLORS.card,
            border: `2.5px solid ${COLORS.ink}`,
            borderRadius: 16,
            boxShadow: SHADOW_CARD,
            overflow: 'hidden',
            position: 'relative',
            transform: `translateY(${interpolate(popB, [0, 1], [50, 0])}px) rotate(1.5deg) scale(${interpolate(popB, [0, 1], [0.94, 1])})`,
            opacity: popB,
          }}
        >
          <div
            style={{
              background: COLORS.red,
              color: '#fff',
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: 32,
              padding: '16px 28px',
            }}
          >
            我的错题本 · 本机
          </div>
          <div style={{ padding: '22px 28px 92px' }}>
            {wrongRows.slice(0, Math.ceil(count / 4)).map((r) => (
              <div
                key={r}
                style={{
                  fontFamily: FONT_BODY,
                  fontSize: 30,
                  color: COLORS.ink,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  lineHeight: 2.1,
                }}
              >
                <span style={{ color: COLORS.red }}>✓</span>
                {r}
              </div>
            ))}
          </div>
          <div
            style={{
              position: 'absolute',
              right: 24,
              bottom: 18,
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: 52,
              color: COLORS.red,
            }}
          >
            {count} 道
          </div>

          <div
            style={{
              position: 'absolute',
              right: 18,
              top: 14,
              width: 96,
              height: 96,
              borderRadius: '50%',
              background: COLORS.card,
              border: `2.5px solid ${COLORS.ink}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: SHADOW_CARD,
              opacity: frame > 162 ? 1 : 0,
              transform: 'rotate(-8deg)',
            }}
          >
            <Stamp delay={162} symbol="✓" size={90} rotate={0} />
          </div>
        </div>
      </div>

      {/* 飞行中的错题小卡片 */}
      {flyers.map(({ p, i }) =>
        p > 0 && p < 1 ? (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: interpolate(p, [0, 1], [700, 1220]),
              top: interpolate(p, [0, 1], [640, 560]) + i * 24,
              width: 250,
              background: COLORS.card,
              border: `2px solid ${COLORS.ink}`,
              borderRadius: 10,
              padding: '10px 20px',
              fontFamily: FONT_BODY,
              fontSize: 26,
              boxShadow: SHADOW_CARD,
              opacity: Math.sin(p * Math.PI),
            }}
          >
            错题 #{i + 1}
          </div>
        ) : null
      )}
    </AbsoluteFill>
  );
};
