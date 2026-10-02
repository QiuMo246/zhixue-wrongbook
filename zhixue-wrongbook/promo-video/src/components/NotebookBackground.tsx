import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';
import { COLORS } from '../theme';

// 方格作业本纸底：官网同款 30px 方格纹理（视频 1080p 下用 40px）
export const NotebookBackground: React.FC = () => {
  const frame = useCurrentFrame();
  // 极缓慢的漂移，让纸面有呼吸感
  const drift = Math.sin(frame / 240) * 6;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.paper,
        backgroundImage: `linear-gradient(rgba(30,42,68,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(30,42,68,0.045) 1px, transparent 1px)`,
        backgroundSize: '40px 40px',
        backgroundPosition: `${drift}px ${drift * 0.6}px`,
      }}
    >
      {/* 左侧红色装订线，作业本感 */}
      <div
        style={{
          position: 'absolute',
          left: 88,
          top: 0,
          bottom: 0,
          width: 2,
          background: 'rgba(224, 69, 58, 0.18)',
        }}
      />
      {/* 四角轻微暗角 */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse at center, transparent 62%, rgba(30,42,68,0.05) 100%)',
        }}
      />
    </AbsoluteFill>
  );
};
