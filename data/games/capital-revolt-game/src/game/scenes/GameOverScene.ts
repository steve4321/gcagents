import * as Phaser from 'phaser';

export class GameOverScene extends Phaser.Scene {
    private score: number = 0;
    private playTime: number = 0;
    private stats: Record<string, number> = {};

    constructor() {
        super({ key: 'GameOverScene' });
    }

    init(data: Record<string, unknown>): void {
        this.score = (data.score as number) || 0;
        this.playTime = (data.playTime as number) || 0;
        this.stats = (data.stats as Record<string, number>) || {};
    }

    create(): void {
        const width = this.cameras.main.width;
        const height = this.cameras.main.height;

        this.add.rectangle(0, 0, width, height, 0x1a1a2e)
            .setOrigin(0)
            .setDepth(-2);

        this.add.text(width / 2, height / 2 - 150, 'GAME OVER', {
            fontFamily: 'Noto Sans SC, Microsoft YaHei, Arial',
            fontSize: '64px',
            fontStyle: 'bold',
            color: '#e94560'
        }).setOrigin(0.5).setDepth(1);

        this.add.text(width / 2, height / 2 - 50, `Score: ${this.score}`, {
            fontFamily: 'Arial',
            fontSize: '36px',
            color: '#ffffff'
        }).setOrigin(0.5).setDepth(1);

        this.add.text(width / 2, height / 2 + 20, `Play Time: ${Math.floor(this.playTime)}s`, {
            fontFamily: 'Arial',
            fontSize: '24px',
            color: '#aaaaaa'
        }).setOrigin(0.5).setDepth(1);

        const buttonWidth = 200;
        const buttonHeight = 50;
        const buttonSpacing = 70;
        const startY = height / 2 + 120;

        [0, 1].forEach(i => {
            const btnBg = this.add.rectangle(width / 2, startY + i * buttonSpacing, buttonWidth, buttonHeight, 0x16213e)
                .setStrokeStyle(2, 0xe94560)
                .setInteractive()
                .setDepth(1);

            const btnLabel = i === 0 ? 'RETRY' : 'MENU';
            const btnText = this.add.text(width / 2, startY + i * buttonSpacing, btnLabel, {
                fontFamily: 'Noto Sans SC, Microsoft YaHei, Arial',
                fontSize: '24px',
                color: '#ffffff'
            }).setOrigin(0.5).setDepth(2);

            btnBg.on('pointerover', () => {
                btnBg.setFillStyle(0xe94560);
            });

            btnBg.on('pointerout', () => {
                btnBg.setFillStyle(0x16213e);
            });

            btnBg.on('pointerdown', () => {
                if (i === 0) {
                    this.retry();
                } else {
                    this.returnToMenu();
                }
            });
        });

        this.reportAnalytics();

        if (typeof window !== 'undefined' && (window as any).__triggerAdBreak) {
            (window as any).__triggerAdBreak();
        }

        this.updateTestInterface();
    }

    private retry(): void {
        this.cameras.main.fade(300, 0, 0, 0);
        this.cameras.main.once('camerafadeoutcomplete', () => {
            this.scene.start('NovelScene');
        });
    }

    private returnToMenu(): void {
        this.cameras.main.fade(300, 0, 0, 0);
        this.cameras.main.once('camerafadeoutcomplete', () => {
            this.scene.start('MenuScene');
        });
    }

    private reportAnalytics(): void {
        if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
            const params = new URLSearchParams({
                game: 'capital_revolt',
                event: 'game_over',
                score: String(this.score),
                play_time: String(Math.floor(this.playTime))
            });
            navigator.sendBeacon('/api/analytics/event', params.toString());
        }
    }

    private updateTestInterface(): void {
        const existingTest = (window as any).__TEST__;
        if (existingTest) {
            const currentState = existingTest.state();
            (window as any).__TEST__ = {
                ...existingTest,
                ready: true,
                state: () => ({
                    ...currentState,
                    currentScene: 'GameOverScene',
                    isGameOver: true
                })
            };
        }
    }

    update(): void {
    }
}
