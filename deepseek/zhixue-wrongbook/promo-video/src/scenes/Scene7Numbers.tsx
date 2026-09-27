import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';

// 分镜7：数字快闪 —— 27 个工具 / 8 类错因 / 341 个知识点 / 332 项自动检查
// （2026-09-27：第四张卡换成大白话措辞以符合学生文案红线；
//   工具数 26→27 因新增 zx_fingerprint_reset；检查数 328→332 因
//   acceptance/mcp_e2e 新增检查项，与 README 同步）
export const Scene7Numbers: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cards = [
    { num: '27', label: '个 MCP 工具', tilt: -0.8 },
    { num: '8', label: '类错因枚举', tilt: 0.6 },
    { num: '341', label: '个受控知识点', tilt: -0.5 },
    { num: '332', label: '项自动检查', tilt: 0.8 },
  ];

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div
        style={{
          fontFamily: FONT_HEAD,
          fontWeight: 900,
          fontSize: 54,
          color: COLORS.ink,
          marginBottom: 70,
          opacity: interpolate(frame, [2, 22], [0, 1], { extrapolateRight: 'clamp' }),
        }}
      >
        不止是同步 —— 一整套<span style={{ color: COLORS.red }}>校验与门禁</span>
      </div>

      <div style={{ display: 'flex', gap: 44 }}>
        {cards.map((c, i) => {
          const p = spring({ frame: frame - 30 - i * 14, fps, config: { damping: 11, mass: 0.7 } });
          return (
            <div
              key={c.label}
              style={{
                background: COLORS.card,
                border: `2.5px solid ${COLORS.ink}`,
                borderRadius: 16,
                boxShadow: '6px 6px 0 rgba(30,42,68,0.16)',
                width: 380,
                padding: '44px 0 36px',
                textAlign: 'center',
                transform: `translateY(${interpolate(p, [0, 1], [70, 0])}px) rotate(${c.tilt}deg) scale(${interpolate(p, [0, 1], [0.9, 1])})`,
                opacity: p,
              }}
            >
              <div
                style={{
                  fontFamily: FONT_HEAD,
                  fontWeight: 900,
                  fontSize: 118,
                  color: COLORS.red,
                  lineHeight: 1.1,
                }}
              >
                {c.num}
              </div>
              <div style={{ fontSize: 32, color: COLORS.inkSoft, marginTop: 12 }}>{c.label}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
