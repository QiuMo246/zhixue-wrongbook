import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_HEAD } from '../theme';

type Props = {
  /** 场景内第几帧盖章 */
  delay: number;
  size?: number;
  rotate?: number;
  symbol?: string; // '×' | '✓'
};

// 红笔盖章：从大缩小压下来，带一点旋转
export const Stamp: React.FC<Props> = ({ delay, size = 220, rotate = -8, symbol = '✓' }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const s = spring({ frame: frame - delay, fps, config: { damping: 10, mass: 0.8 } });
  const scale = interpolate(s, [0, 1], [2.2, 1]);
  const opacity = interpolate(frame - delay, [0, 6], [0, 1], { extrapolateLeft: 'clamp' });

  return (
    <div
      style={{
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transform: `scale(${scale}) rotate(${rotate}deg)`,
        opacity,
        color: COLORS.red,
        fontFamily: FONT_HEAD,
        fontWeight: 900,
        fontSize: size * 0.86,
        lineHeight: 1,
        textShadow: '0 0 0 transparent',
      }}
    >
      {symbol}
    </div>
  );
};
