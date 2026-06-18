import * as Phaser from 'phaser';
import { __GAME_CONFIG__ } from '../config';

export class GameOverScene extends Phaser.Scene {
  isVictory = false;

  constructor() {
    super({ key: 'GameOverScene' });
  }

  init(data: { isVictory: boolean }): void {
    this.isVictory = data.isVictory;
  }

  create(): void {
    const { width, height } = __GAME_CONFIG__.canvas;

    const overlay = this.add.rectangle(0, 0, width, height, 0x000000, 0.7);
    overlay.setOrigin(0);

    const title = this.isVictory ? 'VICTORY!' : 'DEFEAT';
    const color = this.isVictory ? '#2ecc71' : '#e74c3c';

    this.add.text(width / 2, height / 2 - 40, title, {
      fontFamily: 'Arial',
      fontSize: '52px',
      color,
      fontStyle: 'bold',
    }).setOrigin(0.5);

    const subtitle = this.isVictory
      ? 'All waves defeated. Your base stands strong.'
      : 'Your base has fallen. Try again?';
    this.add.text(width / 2, height / 2 + 20, subtitle, {
      fontFamily: 'Arial',
      fontSize: '16px',
      color: '#95a5a6',
    }).setOrigin(0.5);

    const btn = this.add.text(width / 2, height / 2 + 80, 'PLAY AGAIN', {
      fontFamily: 'Arial',
      fontSize: '24px',
      color: '#ffffff',
      fontStyle: 'bold',
      backgroundColor: '#2980b9',
      padding: { x: 32, y: 14 },
    }).setOrigin(0.5);

    btn.setInteractive({ useHandCursor: true });
    btn.on('pointerover', () => btn.setStyle({ backgroundColor: '#3498db' }));
    btn.on('pointerout', () => btn.setStyle({ backgroundColor: '#2980b9' }));
    btn.on('pointerdown', () => {
      this.scene.start('GameScene');
    });
  }
}
