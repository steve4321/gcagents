import * as Phaser from 'phaser';
import { GAME_CONFIG } from '../config';

export class TitleScene extends Phaser.Scene {
    private titleText!: Phaser.GameObjects.Text;
    private subtitleText!: Phaser.GameObjects.Text;
    private pressKeyText!: Phaser.GameObjects.Text;
    private particles: Phaser.GameObjects.Particles.ParticleEmitter | null = null;

    constructor() {
        super('TitleScene');
    }

    create(): void {
        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        const bg = this.add.graphics();
        bg.fillGradientStyle(0x0a0a1a, 0x0a0a1a, 0x1a0a2a, 0x1a0a2a, 1);
        bg.fillRect(0, 0, w, h);

        const grid = this.add.graphics();
        grid.lineStyle(1, 0x00ff88, 0.05);
        for (let x = 0; x < w; x += 40) {
            grid.beginPath();
            grid.moveTo(x, 0);
            grid.lineTo(x, h);
            grid.strokePath();
        }
        for (let y = 0; y < h; y += 40) {
            grid.beginPath();
            grid.moveTo(0, y);
            grid.lineTo(w, y);
            grid.strokePath();
        }

        const particleGfx = this.make.graphics({ x: 0, y: 0, add: false });
        particleGfx.fillStyle(0x00ff88);
        particleGfx.fillCircle(4, 4, 4);
        particleGfx.generateTexture('particle', 8, 8);

        try {
            this.particles = this.add.particles(0, 0, 'particle', {
                x: { min: 0, max: w },
                y: -10,
                lifespan: 4000,
                speedY: { min: 30, max: 80 },
                scale: { start: 0.5, end: 0 },
                alpha: { start: 0.4, end: 0 },
                quantity: 1,
                frequency: 150,
                blendMode: 'ADD'
            });
        } catch (_e) {
            // Phaser 4 particle API compatibility fallback — skip silently
        }

        this.titleText = this.add.text(w / 2, h / 2 - 60, '资本崩塌', {
            fontFamily: font,
            fontSize: '56px',
            fontStyle: 'bold',
            color: '#00ff88',
            stroke: '#003322',
            strokeThickness: 4
        }).setOrigin(0.5);

        this.subtitleText = this.add.text(w / 2, h / 2, '一个关于抵抗的故事', {
            fontFamily: font,
            fontSize: '22px',
            color: '#aaaaaa'
        }).setOrigin(0.5);

        this.pressKeyText = this.add.text(w / 2, h - 80, '点击任意处开始', {
            fontFamily: font,
            fontSize: '18px',
            color: '#666666'
        }).setOrigin(0.5);

        this.tweens.add({
            targets: this.pressKeyText,
            alpha: 0.3,
            duration: 800,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        });

        this.tweens.add({
            targets: this.titleText,
            alpha: 0.85,
            duration: 2000,
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        });

        this.input.keyboard?.once('keydown', () => {
            this.transitionToMenu();
        });

        this.input.on('pointerdown', () => {
            this.transitionToMenu();
        });
    }

    private transitionToMenu(): void {
        this.cameras.main.fadeOut(500, 0, 0, 0);
        this.cameras.main.once('camerafadeoutcomplete', () => {
            this.scene.start('MenuScene');
        });
    }
}
