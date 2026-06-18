import * as Phaser from 'phaser';
import { BootScene } from './game/scenes/BootScene';
import { MenuScene } from './game/scenes/MenuScene';
import { GameScene } from './game/scenes/GameScene';
import { GameOverScene } from './game/scenes/GameOverScene';
import { __GAME_CONFIG__ } from './game/config';

const config: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  width: __GAME_CONFIG__.canvas.width,
  height: __GAME_CONFIG__.canvas.height,
  parent: 'game',
  backgroundColor: '#162416',
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  scene: [BootScene, MenuScene, GameScene, GameOverScene],
};

const game = new Phaser.Game(config);

interface GameTestContract {
  ready: boolean;
  state(): Record<string, unknown>;
  placeTower(col: number, row: number, towerType: string): boolean;
  upgradeTower(col: number, row: number): boolean;
  startNextWave(): boolean;
  getTowerCount(): number;
  getEnemyPositions(): Array<{ x: number; y: number; hp: number; maxHp: number }>;
}

function getGameScene(): GameScene | null {
  return game.scene.getScene('GameScene') as GameScene | null;
}

(window as unknown as { __TEST__: GameTestContract }).__TEST__ = {
  ready: false,

  state() {
    const scene = getGameScene();
    if (!scene || !scene.scene.isActive()) {
      return {
        gold: 0,
        baseHealth: 0,
        maxBaseHealth: __GAME_CONFIG__.base.maxHp,
        currentWave: 0,
        totalWaves: __GAME_CONFIG__.waves.count,
        enemiesAlive: 0,
        towersPlaced: 0,
        isWaveInProgress: false,
        isGameOver: false,
        isVictory: false,
      };
    }
    return {
      gold: scene.getGold(),
      baseHealth: scene.getBaseHealth(),
      maxBaseHealth: __GAME_CONFIG__.base.maxHp,
      currentWave: scene.getCurrentWave(),
      totalWaves: scene.getTotalWaves(),
      enemiesAlive: scene.getEnemiesAlive(),
      towersPlaced: scene.getTowersPlaced(),
      isWaveInProgress: scene.isWaveInProgress(),
      isGameOver: scene.isGameOver,
      isVictory: scene.isVictory,
    };
  },

  placeTower(col: number, row: number, towerType: string): boolean {
    const scene = getGameScene();
    if (!scene || !scene.scene.isActive()) return false;
    return scene.placeTower(col, row, towerType);
  },

  upgradeTower(col: number, row: number): boolean {
    const scene = getGameScene();
    if (!scene || !scene.scene.isActive()) return false;
    return scene.upgradeTower(col, row);
  },

  startNextWave(): boolean {
    const scene = getGameScene();
    if (!scene || !scene.scene.isActive()) return false;
    return scene.startNextWave();
  },

  getTowerCount(): number {
    const scene = getGameScene();
    if (!scene || !scene.scene.isActive()) return 0;
    return scene.getTowersPlaced();
  },

  getEnemyPositions(): Array<{ x: number; y: number; hp: number; maxHp: number }> {
    const scene = getGameScene();
    if (!scene || !scene.scene.isActive()) return [];
    return scene.getEnemyPositions();
  },
};

game.events.once('ready', () => {
  (window as unknown as { __TEST__: GameTestContract }).__TEST__.ready = true;
});
