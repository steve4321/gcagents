import { VN_WIDTH, VN_HEIGHT } from '../config';

export class TitleScene extends Phaser.Scene {
  constructor() {
    super({ key: 'TitleScene' });
  }

  create(): void {
    this.add.text(VN_WIDTH / 2, VN_HEIGHT / 2 - 80, 'Visual Novel', {
      fontSize: '64px',
      color: '#ffffff',
      fontFamily: 'serif',
    }).setOrigin(0.5);

    this.add.text(VN_WIDTH / 2, VN_HEIGHT / 2 + 40, 'Click to start', {
      fontSize: '24px',
      color: '#aaaaaa',
      fontFamily: 'sans-serif',
    }).setOrigin(0.5);

    this.input.once('pointerdown', () => this.scene.start('MenuScene'));
  }
}
