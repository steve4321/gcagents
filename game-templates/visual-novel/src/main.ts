import { BootScene } from './game/scenes/BootScene';
import { TitleScene } from './game/scenes/TitleScene';
import { MenuScene } from './game/scenes/MenuScene';
import { NovelScene } from './game/scenes/NovelScene';
import { VN_WIDTH, VN_HEIGHT } from './game/config';
import { DialogueSystem } from './game/systems/DialogueSystem';

const config: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  width: VN_WIDTH,
  height: VN_HEIGHT,
  parent: 'game-container',
  backgroundColor: '#0a0a14',
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  scene: [BootScene, TitleScene, MenuScene, NovelScene],
};

const game = new Phaser.Game(config);

declare global {
  interface Window {
    __TEST__?: {
      ready: boolean;
      state: () => Record<string, unknown>;
      setLocale: (locale: string) => void;
      unlockCG: (key: string) => void;
      getStateHash: () => string;
      save: (slot: number) => void;
      load: (slot: number) => void;
    };
  }
}

window.__TEST__ = {
  ready: false,
  state: () => {
    const scene = game.scene.getScene('NovelScene') as NovelScene | null;
    if (!scene) {
      return { currentScene: '(none)', currentRoute: '', stats: {}, flags: [], cgsUnlocked: [], routeProgress: {}, endingReached: null, saveDataValid: false, visitedScenes: [], endingsReached: [] };
    }
    return scene.getTestState();
  },
  setLocale: (_locale: string) => undefined,
  unlockCG: (_key: string) => undefined,
  getStateHash: () => '',
  save: (_slot: number) => undefined,
  load: (_slot: number) => undefined,
};

export { game, DialogueSystem, NovelScene };
