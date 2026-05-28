// Phaser 4 Idle Clicker Template
// Entry point - bootstraps the game

import { BootScene } from './game/scenes/BootScene';
import { MenuScene } from './game/scenes/MenuScene';
import { GameScene } from './game/scenes/GameScene';
import { GameOverScene } from './game/scenes/GameOverScene';

const config: Phaser.Types.Core.GameConfig = {
    type: Phaser.AUTO,
    width: 800,
    height: 600,
    parent: 'game',
    backgroundColor: '#1a1a2e',
    scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    scene: [BootScene, MenuScene, GameScene, GameOverScene],
};

const game = new Phaser.Game(config);

(window as any).__TEST__ = {
    ready: false,
    state: () => {
        const scene = game.scene.getScene('GameScene');
        return {
            score: (scene as any).score ?? 0,
            clickPower: (scene as any).clickPower ?? 1,
            upgradeLevel: (scene as any).upgradeLevel ?? 0,
        };
    },
};
