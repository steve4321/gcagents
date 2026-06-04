import { VN_WIDTH, VN_HEIGHT } from '../config';

export class MenuScene extends Phaser.Scene {
  constructor() {
    super({ key: 'MenuScene' });
  }

  create(): void {
    const items = ['NEW GAME', 'CONTINUE', 'GALLERY', 'SETTINGS'];
    const startY = VN_HEIGHT / 2 - (items.length * 50) / 2;

    items.forEach((label, i) => {
      const y = startY + i * 50;
      const text = this.add.text(VN_WIDTH / 2, y, label, {
        fontSize: '28px',
        color: '#ffffff',
        fontFamily: 'sans-serif',
      }).setOrigin(0.5).setInteractive({ useHandCursor: true });

      text.on('pointerover', () => text.setColor('#ffdd88'));
      text.on('pointerout', () => text.setColor('#ffffff'));
      text.on('pointerdown', () => {
        if (i === 0) this.scene.start('NovelScene');
      });
    });
  }
}
