import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, SHADOW_CARD } from '../theme';

type Props = {
  side: 'user' | 'ai';
  text: string;
  /** 场景内第几帧开始出现 */
  delay: number;
  /** 打字机每帧出几个字 */
  cps?: number;
  width?: number | string;
};

// 聊天气泡：user 右侧墨蓝底白字，ai 左侧白卡纸片；文字打字机逐字出现
export const DialogueBubble: React.FC<Props> = ({ side, text, delay, cps = 0.7, width = 640 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const pop = spring({ frame: frame - delay, fps, config: { damping: 14, mass: 0.6 } });
  const chars = Math.max(0, Math.floor((frame - delay - 8) * cps));
  const shown = text.slice(0, chars);

  const isUser = side === 'user';

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        transform: `translateY(${interpolate(pop, [0, 1], [30, 0])}px) scale(${interpolate(pop, [0, 1], [0.92, 1])})`,
        opacity: interpolate(pop, [0, 1], [0, 1]),
      }}
    >
      <div
        style={{
          maxWidth: width,
          background: isUser ? COLORS.ink : COLORS.card,
          color: isUser ? '#fff' : COLORS.ink,
          border: `2.5px solid ${COLORS.ink}`,
          borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
          boxShadow: SHADOW_CARD,
          padding: '22px 34px',
          fontFamily: FONT_BODY,
          fontSize: 38,
          lineHeight: 1.5,
          transform: `rotate(${isUser ? 0.4 : -0.4}deg)`,
          minHeight: 38 * 1.5,
        }}
      >
        {shown}
        {/* 打字光标 */}
        {chars < text.length && chars > 0 ? (
          <span style={{ color: COLORS.red, fontWeight: 700 }}>▏</span>
        ) : null}
      </div>
    </div>
  );
};
