// Boot scene - loads assets and transitions to menu

export class BootScene extends Phaser.Scene {
    constructor() {
        super({ key: 'BootScene' });
    }

    preload(): void {
        const { width, height } = this.scale;
        const barWidth = 300;
        const barHeight = 20;
        const x = (width - barWidth) / 2;
        const y = height / 2;

        const bg = this.add.graphics();
        bg.fillStyle(0x333333, 1);
        bg.fillRect(x, y, barWidth, barHeight);

        const bar = this.add.graphics();

        this.load.on('progress', (value: number) => {
            bar.clear();
            bar.fillStyle(0x00ff88, 1);
            bar.fillRect(x, y, barWidth * value, barHeight);
        });

        this.load.on('complete', () => {
            this.scene.start('MenuScene');
        });

        this.load.setBaseURL('/');
    }

    create(): void {
        // No external assets for template - auto-complete
        this.load.start();
    }
}
