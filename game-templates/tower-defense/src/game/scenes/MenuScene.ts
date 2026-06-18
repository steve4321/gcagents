import * as Phaser from 'phaser';
import { __GAME_CONFIG__ } from '../config';

export class MenuScene extends Phaser.Scene {
  constructor() {
    super({ key: 'MenuScene' });
  }

  create(): void {
    const { width, height } = __GAME_CONFIG__.canvas;

    this.add.rectangle(0, 0, width, height, 0x1a1a2e).setOrigin(0);

    this.add.text(width / 2, height / 2 - 60, 'TOWER DEFENSE', {
      fontFamily: 'Arial',
      fontSize: '42px',
      color: '#ecf0f1',
      fontStyle: 'bold',
    }).setOrigin(0.5);

    this.add.text(width / 2, height / 2 - 10, 'Place towers. Stop waves. Defend your base.', {
      fontFamily: 'Arial',
      fontSize: '16px',
      color: '#95a5a6',
    }).setOrigin(0.5);

    const btn = this.add.text(width / 2, height / 2 + 60, 'START', {
      fontFamily: 'Arial',
      fontSize: '28px',
      color: '#ffffff',
      fontStyle: 'bold',
      backgroundColor: '#27ae60',
      padding: { x: 40, y: 16 },
    }).setOrigin(0.5);

    btn.setInteractive({ useHandCursor: true });
    btn.on('pointerover', () => btn.setStyle({ backgroundColor: '#2ecc71' }));
    btn.on('pointerout', () => btn.setStyle({ backgroundColor: '#27ae60' }));
    btn.on('pointerdown', () => {
      this.scene.start('GameScene');
    });
  }
}
