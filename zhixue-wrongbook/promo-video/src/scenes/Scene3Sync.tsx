import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { COLORS, FONT_BODY, FONT_HEAD } from '../theme';
import { DialogueBubble } from '../components/DialogueBubble';
import { Stamp } from '../components/Stamp';

// 分镜3 对话①：同步错题 —— 三条通道兜底
export const Scene3Sync: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const channels = [
    { name: '官方导出', desc: '官网导出包直接读' },
    { name: '现成库', desc: '开源接口优先接' },
    { name: '自建接口', desc: '浏览器采集中转兜底' },
  ];

  const done = spring({ frame: frame - 130, fps, config: { damping: 14 } });

  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 1160, display: 'flex', flexDirection: 'column', gap: 26 }}>
        <DialogueBubble side="user" text="帮我同步错题" delay={8} width={520} />

        <div
          style={{
            display: 'flex',
            gap: 28,
            marginTop: 16,
            justifyContent: 'center',
          }}
        >
          {channels.map((c, i) => {
            const p = spring({ frame: frame - 60 - i * 16, fps, config: { damping: 14 } });
            return (
              <div
                key={c.name}
                style={{
                  flex: 1,
                  background: COLORS.card,
                  border: `2.5px solid ${COLORS.ink}`,
                  borderRadius: 14,
                  boxShadow: '5px 5px 0 rgba(30,42,68,0.16)',
                  padding: '30px 34px',
                  transform: `translateY(${interpolate(p, [0, 1], [46, 0])}px) rotate(${i % 2 === 0 ? -0.5 : 0.5}deg)`,
                  opacity: p,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 10 }}>
                  <span
                    style={{
                      fontSize: 26,
                      color: '#fff',
                      background: COLORS.blue,
                      borderRadius: 6,
                      padding: '2px 12px',
                      fontFamily: FONT_HEAD,
                      fontWeight: 900,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    通道{['一', '二', '三'][i]}
                  </span>
                  <span
                    style={{
                      fontFamily: FONT_HEAD,
                      fontWeight: 900,
                      fontSize: 42,
                      color: COLORS.ink,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {c.name}
                  </span>
                </div>
                <div style={{ fontSize: 30, color: COLORS.inkSoft }}>{c.desc}</div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-start',
            marginTop: 18,
            opacity: interpolate(done, [0, 1], [0, 1]),
            transform: `scale(${interpolate(done, [0, 1], [0.9, 1])})`,
            transformOrigin: 'left center',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 20,
              background: COLORS.card,
              border: `2.5px solid ${COLORS.ink}`,
              borderRadius: 12,
              padding: '20px 36px',
              fontFamily: FONT_HEAD,
              fontWeight: 900,
              fontSize: 40,
              transform: 'rotate(-0.6deg)',
            }}
          >
            <span style={{ color: COLORS.red, fontSize: 48 }}>✓</span>
            同步完成，错题已入库
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
