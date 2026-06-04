export class GameOverScene extends Phaser.Scene {
    constructor() {
        super({ key: 'GameOverScene' });
    }

    create(): void {
        const { width, height } = this.scale;

        this.add.text(width / 2, height / 3, 'GAME OVER', {
            fontSize: '42px',
            color: '#ff4444',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        const finalScore = this.registry.get('finalScore') ?? 0;
        this.add.text(width / 2, height / 2, `Final Score: ${finalScore}`, {
            fontSize: '24px',
            color: '#ffffff',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        const btn = this.add.text(width / 2, height * 0.7, '[ PLAY AGAIN ]', {
            fontSize: '24px',
            color: '#00ff88',
            fontFamily: 'monospace',
            backgroundColor: '#333355',
            padding: { x: 20, y: 10 },
        }).setOrigin(0.5).setInteractive({ useHandCursor: true });

        btn.on('pointerdown', () => this.scene.start('MenuScene'));
    }
}
