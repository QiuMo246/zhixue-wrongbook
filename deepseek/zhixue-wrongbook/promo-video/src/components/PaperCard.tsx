import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, SHADOW_CARD, SHADOW_HARD } from '../theme';

type Props = {
  children: React.ReactNode;
  delay?: number;
  tilt?: number; // 手写歪斜角度
  hardShadow?: boolean;
  style?: React.CSSProperties;
  dropFrom?: number; // 拍落距离
};

// 官网同款「纸片卡」：白底 + 墨蓝描边 + 硬阴影 + 轻微歪斜，spring 拍落入场
export const PaperCard: React.FC<Props> = ({
  children,
  delay = 0,
  tilt = 0,
  hardShadow = false,
  style,
  dropFrom = 60,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame: frame - delay, fps, config: { damping: 15, mass: 0.9 } });

  return (
    <div
      style={{
        background: COLORS.card,
        border: `2.5px solid ${COLORS.ink}`,
        borderRadius: 18,
        boxShadow: hardShadow ? SHADOW_HARD : SHADOW_CARD,
        padding: '36px 48px',
        fontFamily: FONT_BODY,
        color: COLORS.ink,
        transform: `translateY(${interpolate(pop, [0, 1], [dropFrom, 0])}px) scale(${interpolate(pop, [0, 1], [0.95, 1])}) rotate(${tilt}deg)`,
        opacity: interpolate(pop, [0, 1], [0, 1]),
        ...style,
      }}
    >
      {children}
    </div>
  );
};
