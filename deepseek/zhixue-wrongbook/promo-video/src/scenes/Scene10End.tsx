import React from 'react';
import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { COLORS, FONT_HEAD } from '../theme';

const NAME = 'QiuMo';
const LETTERS = NAME.split('');

// 快-慢曲线（ease-out）：t=0 速度最高，随后单调衰减到 0，
// 曲线尾部长，所以末段是「滑行收住」而非「到位急停」。
const FAST_ROUND: [number, number, number, number] = [0.16, 0.86, 0.24, 1];
const FAST_HARD: [number, number, number, number] = [0.11, 0.9, 0.18, 1];

// 持续微漂移：相位按元素错开，永不同步，避免画面出现「结束状态」
const micro = (frame: number, phase: number, amp: number, period: number) =>
  Math.sin(((frame + phase) / period) * Math.PI * 2) * amp;

// 名字：逐字上浮，错峰 6 帧
const QiuMoName: React.FC<{ delay: number; size?: number; color?: string }> = ({
  delay,
  size = 130,
  color = COLORS.ink,
}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ display: 'flex', gap: size * 0.012 }}>
      {LETTERS.map((ch, i) => {
        const at = delay + i * 6;
        const f = interpolate(frame, [at, at + 40], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: Easing.bezier(...FAST_ROUND),
        });
        return (
          <span
            key={i}
            style={{
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: size,
              color,
              lineHeight: 1,
              display: 'inline-block',
              transform: `translateY(${interpolate(f, [0, 1], [44, 0])}px) translateY(${micro(frame, i * 13, 5, 52 + i * 7)}px)`,
              opacity: f,
            }}
          >
            {ch}
          </span>
        );
      })}
    </div>
  );
};

// 头像：圆形墨蓝描边 + 硬阴影，与官网纸片卡同一套语言
const Avatar: React.FC<{ size: number }> = ({ size }) => (
  <div
    style={{
      width: size,
      height: size,
      borderRadius: '50%',
      border: `7px solid ${COLORS.ink}`,
      background: COLORS.card,
      boxShadow: '9px 9px 0 rgba(30,42,68,0.9)',
      overflow: 'hidden',
      flexShrink: 0,
    }}
  >
    <img src={staticFile('avatar.webp')} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
  </div>
);

// 分镜11· 片尾署名 —— 头像自下升起并放大（快-慢曲线），QiuMo 同步浮现
export const Scene10End: React.FC = () => {
  const frame = useCurrentFrame();

  const s = interpolate(frame, [0, 74], [0.1, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(...FAST_ROUND),
  });
  // 纵移用更猛的曲线，视觉重心先稳下来
  const y = interpolate(frame, [0, 52], [300, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(...FAST_HARD),
  });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 56 }}>
        <div style={{ transform: `translateY(${y}px) scale(${s})` }}>
          <Avatar size={300} />
        </div>
        <div
          style={{
            opacity: interpolate(frame, [8, 40], [0, 1], {
              extrapolateRight: 'clamp',
              easing: Easing.bezier(...FAST_ROUND),
            }),
          }}
        >
          <QiuMoName delay={10} size={130} />
        </div>
      </div>
    </AbsoluteFill>
  );
};