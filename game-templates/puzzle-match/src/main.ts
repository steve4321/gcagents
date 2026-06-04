// Phaser 4 Puzzle Match Template
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
        const scene = game.scene.getScene('GameScene') as GameScene;
        return {
            score: scene.score ?? 0,
            timeLeft: scene.timeLeft ?? 60,
            gridSize: 8,
            moves: scene.moves ?? 0,
        };
    },
};

export { GameScene };
