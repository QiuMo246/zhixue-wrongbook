import React from 'react';
import { AbsoluteFill, Composition, Sequence } from 'remotion';
import { NotebookBackground } from './components/NotebookBackground';
import { SCENES, VIDEO } from './theme';
import { Scene0Hook } from './scenes/Scene0Hook';
import { Scene1Intro } from './scenes/Scene1Intro';
import { Scene2Title } from './scenes/Scene2Title';
import { Scene3Sync } from './scenes/Scene3Sync';
import { Scene4Diagnose } from './scenes/Scene4Diagnose';
import { Scene5Paper } from './scenes/Scene5Paper';
import { Scene6Grade } from './scenes/Scene6Grade';
import { Scene7Numbers } from './scenes/Scene7Numbers';
import { Scene8Privacy } from './scenes/Scene8Privacy';
import { Scene9CTA } from './scenes/Scene9CTA';
import { Scene10End } from './scenes/Scene10End';
import { AudioTrack } from './components/AudioTrack';

const Scene: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>{children}</AbsoluteFill>
);

export const Promo: React.FC = () => {
  return (
    <AbsoluteFill>
      <NotebookBackground />
      <AudioTrack />
      <Scene><Sequence from={SCENES.hook.from} durationInFrames={SCENES.hook.duration}><Scene0Hook /></Sequence></Scene>
      <Scene><Sequence from={SCENES.intro.from} durationInFrames={SCENES.intro.duration}><Scene1Intro /></Sequence></Scene>
      <Scene><Sequence from={SCENES.title.from} durationInFrames={SCENES.title.duration}><Scene2Title /></Sequence></Scene>
      <Scene><Sequence from={SCENES.sync.from} durationInFrames={SCENES.sync.duration}><Scene3Sync /></Sequence></Scene>
      <Scene><Sequence from={SCENES.diagnose.from} durationInFrames={SCENES.diagnose.duration}><Scene4Diagnose /></Sequence></Scene>
      <Scene><Sequence from={SCENES.paper.from} durationInFrames={SCENES.paper.duration}><Scene5Paper /></Sequence></Scene>
      <Scene><Sequence from={SCENES.grade.from} durationInFrames={SCENES.grade.duration}><Scene6Grade /></Sequence></Scene>
      <Scene><Sequence from={SCENES.numbers.from} durationInFrames={SCENES.numbers.duration}><Scene7Numbers /></Sequence></Scene>
      <Scene><Sequence from={SCENES.privacy.from} durationInFrames={SCENES.privacy.duration}><Scene8Privacy /></Sequence></Scene>
      <Scene><Sequence from={SCENES.cta.from} durationInFrames={SCENES.cta.duration}><Scene9CTA /></Sequence></Scene>
      <Scene><Sequence from={SCENES.end.from} durationInFrames={SCENES.end.duration}><Scene10End /></Sequence></Scene>
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Promo"
        component={Promo}
        width={VIDEO.width}
        height={VIDEO.height}
        fps={VIDEO.fps}
        durationInFrames={VIDEO.durationInFrames}
      />
    </>
  );
};
