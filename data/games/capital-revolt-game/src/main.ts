import * as Phaser from 'phaser';
import { BootScene } from './game/scenes/BootScene';
import { TitleScene } from './game/scenes/TitleScene';
import { MenuScene } from './game/scenes/MenuScene';
import { NovelScene } from './game/scenes/NovelScene';

const config: Phaser.Types.Core.GameConfig = {
    type: Phaser.AUTO,
    parent: 'game-container',
    width: 800,
    height: 600,
    backgroundColor: '#050510',
    scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH
    },
    scene: [
        BootScene,
        TitleScene,
        MenuScene,
        NovelScene
    ]
};

new Phaser.Game(config);

export {};

declare global {
    interface Window {
        __TEST__?: {
            ready: boolean;
            state: () => {
                currentScene: string;
                currentRoute: string;
                stats: Record<string, number>;
                flags: Record<string, boolean>;
                cgsUnlocked: string[];
                routeProgress: Record<string, number>;
                endingReached: string | null;
                saveDataValid: boolean;
                visitedScenes: string[];
                endingsReached: string[];
                sessionTime: number;
            };
        };
    }
}
