export class MenuScene extends Phaser.Scene {
    constructor() {
        super({ key: 'MenuScene' });
    }

    create(): void {
        const { width, height } = this.scale;

        this.add.text(width / 2, height / 3, 'IDLE CLICKER', {
            fontSize: '48px',
            color: '#00ff88',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        this.add.text(width / 2, height / 3 + 60, 'Click to earn, upgrade to grow!', {
            fontSize: '18px',
            color: '#aaaaaa',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        const btn = this.add.text(width / 2, height * 0.6, '[ START ]', {
            fontSize: '32px',
            color: '#ffffff',
            fontFamily: 'monospace',
            backgroundColor: '#333355',
            padding: { x: 30, y: 15 },
        }).setOrigin(0.5).setInteractive({ useHandCursor: true });

        btn.on('pointerover', () => btn.setStyle({ color: '#00ff88' }));
        btn.on('pointerout', () => btn.setStyle({ color: '#ffffff' }));
        btn.on('pointerdown', () => this.scene.start('GameScene'));
    }
}
