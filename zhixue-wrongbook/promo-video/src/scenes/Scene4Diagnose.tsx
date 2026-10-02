import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';
import { DialogueBubble } from '../components/DialogueBubble';
import { PaperCard } from '../components/PaperCard';

// 分镜4 对话②：薄弱项诊断 —— 诊断闸门先问范围
export const Scene4Diagnose: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const weak = [
    { name: '浮力', pct: 72 },
    { name: '电路', pct: 55 },
    { name: '压强', pct: 40 },
  ];

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 1160, display: 'flex', flexDirection: 'column', gap: 22 }}>
        <DialogueBubble side="user" text="帮我分析薄弱项" delay={6} width={520} />

        {/* 诊断闸门卡片（红框警示） */}
        <PaperCard delay={48} tilt={-0.5} style={{ border: `3px solid ${COLORS.red}`, padding: '28px 40px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
            <span
              style={{
                fontFamily: FONT_HEAD,
                fontWeight: 900,
                fontSize: 36,
                color: '#fff',
                background: COLORS.red,
                borderRadius: 8,
                padding: '6px 18px',
              }}
            >
              诊断闸门
            </span>
            <span style={{ fontFamily: FONT_HEAD, fontWeight: 900, fontSize: 40 }}>
              不问清范围，不给数据
            </span>
          </div>
          <div style={{ marginTop: 18, display: 'flex', gap: 18 }}>
            {['哪个科目？', '哪些考试？'].map((q, i) => (
              <span
                key={q}
                style={{
                  fontSize: 30,
                  color: COLORS.red,
                  border: `2px dashed ${COLORS.red}`,
                  borderRadius: 999,
                  padding: '6px 24px',
                  opacity: interpolate(frame, [78 + i * 10, 92 + i * 10], [0, 1], {
                    extrapolateLeft: 'clamp',
                    extrapolateRight: 'clamp',
                  }),
                }}
              >
                {q}
              </span>
            ))}
          </div>
        </PaperCard>

        <DialogueBubble side="user" text="九上物理，近三次考试" delay={118} width={560} />

        {/* 薄弱项画像 */}
        <div style={{ marginTop: 6 }}>
          {weak.map((w, i) => {
            const p = spring({ frame: frame - 160 - i * 12, fps, config: { damping: 16 } });
            return (
              <div key={w.name} style={{ display: 'flex', alignItems: 'center', gap: 24, marginBottom: 14 }}>
                <span style={{ fontFamily: FONT_HEAD, fontWeight: 900, fontSize: 34, width: 130 }}>
                  {w.name}
                </span>
                <div
                  style={{
                    flex: 1,
                    height: 26,
                    background: 'rgba(30,42,68,0.08)',
                    borderRadius: 999,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${w.pct * p}%`,
                      height: '100%',
                      background: COLORS.red,
                      borderRadius: 999,
                    }}
                  />
                </div>
                <span style={{ fontSize: 30, color: COLORS.inkSoft, width: 90, textAlign: 'right' }}>
                  {Math.round(w.pct * p)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
