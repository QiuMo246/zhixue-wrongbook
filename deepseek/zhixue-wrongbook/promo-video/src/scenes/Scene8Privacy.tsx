import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD, SHADOW_CARD } from '../theme';

// 分镜8：隐私 —— 数据全在自己电脑上
export const Scene8Privacy: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const pop = spring({ frame: frame - 8, fps, config: { damping: 14 } });
  const items = ['凭据进系统凭据管理器', '可配本地模型', '不上传任何云端'];

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      {/* 简笔笔记本电脑 + 锁 */}
      <div
        style={{
          position: 'relative',
          width: 300,
          height: 210,
          marginBottom: 56,
          transform: `translateY(${interpolate(pop, [0, 1], [40, 0])}px)`,
          opacity: pop,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 20,
            top: 0,
            width: 260,
            height: 160,
            border: `3px solid ${COLORS.ink}`,
            borderRadius: 12,
            background: COLORS.card,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 0,
            bottom: 18,
            width: 300,
            height: 26,
            border: `3px solid ${COLORS.ink}`,
            borderRadius: 8,
            background: COLORS.card,
          }}
        />
        <div
          style={{
            position: 'absolute',
            right: 52,
            top: -46,
            fontSize: 84,
            color: COLORS.red,
            fontFamily: FONT_HEAD,
            fontWeight: 900,
            transform: 'rotate(-8deg)',
          }}
        >
          🔒
        </div>
      </div>

      <div
        style={{
          fontFamily: FONT_HEAD,
          fontWeight: 900,
          fontSize: 84,
          color: COLORS.ink,
          opacity: interpolate(frame, [20, 45], [0, 1], { extrapolateRight: 'clamp' }),
        }}
      >
        数据全在<span style={{ color: COLORS.red }}>你自己电脑</span>上
      </div>

      <div style={{ display: 'flex', gap: 26, marginTop: 52 }}>
        {items.map((t, i) => (
          <div
            key={t}
            style={{
              fontSize: 30,
              fontFamily: FONT_BODY,
              color: COLORS.ink,
              background: COLORS.card,
              border: `2px solid ${COLORS.ink}`,
              borderRadius: 999,
              padding: '10px 30px',
              boxShadow: SHADOW_CARD,
              transform: `rotate(${i % 2 === 0 ? -0.5 : 0.5}deg)`,
              opacity: interpolate(frame, [48 + i * 10, 66 + i * 10], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
            }}
          >
            {t}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
