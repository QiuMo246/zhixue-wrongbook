// 与官网 web/src/style.css 对齐的设计 token（1920×1080 视频按 ~1.4x 放大阴影/纹理）
export const COLORS = {
  paper: '#fbfaf6',
  ink: '#1e2a44',
  inkSoft: 'rgba(30, 42, 68, 0.66)',
  inkFaint: 'rgba(30, 42, 68, 0.14)',
  red: '#e0453a',
  redDeep: '#c2352b',
  yellow: '#ffe24a',
  blue: '#3a7bd5',
  card: '#ffffff',
};

export const FONT_HEAD = '"MiSans", system-ui, "Microsoft YaHei", "PingFang SC", sans-serif';
export const FONT_BODY = 'system-ui, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif';
export const FONT_MONO = '"Cascadia Code", Consolas, monospace';

export const SHADOW_HARD = '7px 7px 0 rgba(30, 42, 68, 0.9)';
export const SHADOW_CARD = '5px 5px 0 rgba(30, 42, 68, 0.16)';

export const VIDEO = {
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 2190,
};

// 每个分镜的起始帧（fps=30，总计 73s / 2190 帧）
export const SCENES = {
  hook: { from: 0, duration: 270 },
  intro: { from: 270, duration: 180 },
  title: { from: 450, duration: 180 },
  sync: { from: 630, duration: 210 },
  diagnose: { from: 840, duration: 240 },
  paper: { from: 1080, duration: 240 },
  grade: { from: 1320, duration: 210 },
  numbers: { from: 1530, duration: 210 },
  privacy: { from: 1740, duration: 150 },
  cta: { from: 1890, duration: 180 },
  end: { from: 2070, duration: 120 },
};
