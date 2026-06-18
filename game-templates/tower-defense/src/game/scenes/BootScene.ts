import * as Phaser from 'phaser';

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: 'BootScene' });
  }

  create(): void {
    this.generateTextures();
    this.scene.start('MenuScene');
  }

  private generateTextures(): void {
    this.makeTowerTexture('tower_arrow', 0x27ae60, 'triangle');
    this.makeTowerTexture('tower_cannon', 0xe74c3c, 'square');
    this.makeTowerTexture('tower_frost', 0x3498db, 'hexagon');

    this.makeCircleTexture('enemy_runner', 10, 0xf7d51d);
    this.makeCircleTexture('enemy_brute', 13, 0xe8743b);
    this.makeCircleTexture('enemy_tank', 16, 0x9b59b6);

    this.makeBaseTexture();
  }

  private makeTowerTexture(key: string, color: number, shape: string): void {
    const size = 32;
    const gfx = this.make.graphics({ x: 0, y: 0 });

    if (shape === 'triangle') {
      gfx.fillStyle(color);
      gfx.fillTriangle(size / 2, 4, 4, size - 4, size - 4, size - 4);
      gfx.lineStyle(2, 0xffffff, 0.5);
      gfx.strokeTriangle(size / 2, 4, 4, size - 4, size - 4, size - 4);
    } else if (shape === 'square') {
      gfx.fillStyle(color);
      gfx.fillRect(4, 4, size - 8, size - 8);
      gfx.lineStyle(2, 0xffffff, 0.5);
      gfx.strokeRect(4, 4, size - 8, size - 8);
    } else if (shape === 'hexagon') {
      gfx.fillStyle(color);
      const cx = size / 2;
      const cy = size / 2;
      const r = size / 2 - 4;
      const points: number[] = [];
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 2;
        points.push(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
      }
      gfx.beginPath();
      gfx.moveTo(points[0], points[1]);
      for (let i = 2; i < points.length; i += 2) {
        gfx.lineTo(points[i], points[i + 1]);
      }
      gfx.closePath();
      gfx.fillPath();
      gfx.lineStyle(2, 0xffffff, 0.5);
      gfx.strokePath();
    }

    gfx.generateTexture(key, size, size);
    gfx.destroy();
  }

  private makeCircleTexture(key: string, radius: number, color: number): void {
    const size = (radius + 2) * 2;
    const gfx = this.make.graphics({ x: 0, y: 0 });
    gfx.fillStyle(color);
    gfx.fillCircle(size / 2, size / 2, radius);
    gfx.lineStyle(2, 0x000000, 0.4);
    gfx.strokeCircle(size / 2, size / 2, radius);
    gfx.generateTexture(key, size, size);
    gfx.destroy();
  }

  private makeBaseTexture(): void {
    const gfx = this.make.graphics({ x: 0, y: 0 });
    gfx.fillStyle(0x2c3e50);
    gfx.fillRect(2, 8, 32, 28);
    gfx.lineStyle(3, 0xecf0f1);
    gfx.strokeRect(2, 8, 32, 28);
    gfx.fillStyle(0xe74c3c);
    gfx.fillTriangle(18, 0, 0, 12, 36, 12);
    gfx.generateTexture('base', 36, 40);
    gfx.destroy();
  }
}
