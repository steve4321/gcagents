export class GameScene extends Phaser.Scene {
    score = 0;
    clickPower = 1;
    upgradeLevel = 0;
    upgradeCost = 10;
    autoClickRate = 0;
    autoClickLevel = 0;
    autoClickCost = 50;

    private scoreText!: Phaser.GameObjects.Text;
    private clickButton!: Phaser.GameObjects.Container;
    private particles!: Phaser.GameObjects.Particles.ParticleEmitter;

    create(): void {
        const { width, height } = this.scale;

        this.scoreText = this.add.text(width / 2, 40, 'Score: 0', {
            fontSize: '28px',
            color: '#ffffff',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        this._createClickButton(width / 2, height / 2 - 30);
        this._createUpgradeButtons(width, height);

        (window as any).__TEST__!.ready = true;
    }

    update(_time: number, delta: number): void {
        if (this.autoClickRate > 0) {
            this.score += this.autoClickRate * (delta / 1000);
            this._updateScore();
        }
    }

    private _createClickButton(x: number, y: number): void {
        const circle = this.add.circle(0, 0, 60, 0x00ff88, 0.3);
        circle.setStrokeStyle(3, 0x00ff88);

        const label = this.add.text(0, 0, 'CLICK', {
            fontSize: '20px',
            color: '#00ff88',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        this.clickButton = this.add.container(x, y, [circle, label]);
        this.clickButton.setSize(120, 120);
        this.clickButton.setInteractive({ useHandCursor: true });

        this.clickButton.on('pointerdown', () => {
            this.score += this.clickPower;
            this._updateScore();
            this._spawnClickEffect(x, y);
        });
    }

    private _createUpgradeButtons(width: number, height: number): void {
        const upgradeBtn = this.add.text(50, height - 120, `Click Power: +1\nCost: ${this.upgradeCost}`, {
            fontSize: '14px',
            color: '#ffaa00',
            fontFamily: 'monospace',
            backgroundColor: '#332200',
            padding: { x: 10, y: 8 },
        }).setInteractive({ useHandCursor: true });

        upgradeBtn.on('pointerdown', () => {
            if (this.score >= this.upgradeCost) {
                this.score -= this.upgradeCost;
                this.clickPower += 1;
                this.upgradeLevel += 1;
                this.upgradeCost = Math.floor(10 * Math.pow(1.5, this.upgradeLevel));
                upgradeBtn.setText(`Click Power: +1\nCost: ${this.upgradeCost}`);
                this._updateScore();
            }
        });

        const autoBtn = this.add.text(width - 200, height - 120, `Auto Click: 0/s\nCost: ${this.autoClickCost}`, {
            fontSize: '14px',
            color: '#aa00ff',
            fontFamily: 'monospace',
            backgroundColor: '#220033',
            padding: { x: 10, y: 8 },
        }).setInteractive({ useHandCursor: true });

        autoBtn.on('pointerdown', () => {
            if (this.score >= this.autoClickCost) {
                this.score -= this.autoClickCost;
                this.autoClickRate += 1;
                this.autoClickLevel += 1;
                this.autoClickCost = Math.floor(50 * Math.pow(1.8, this.autoClickLevel));
                autoBtn.setText(`Auto Click: ${this.autoClickRate}/s\nCost: ${this.autoClickCost}`);
                this._updateScore();
            }
        });
    }

    private _spawnClickEffect(x: number, y: number): void {
        const text = this.add.text(x + Phaser.Math.Between(-30, 30), y - 40, `+${this.clickPower}`, {
            fontSize: '18px',
            color: '#ffff00',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        this.tweens.add({
            targets: text,
            y: y - 100,
            alpha: 0,
            duration: 600,
            ease: 'Power2',
            onComplete: () => text.destroy(),
        });
    }

    private _updateScore(): void {
        this.scoreText.setText(`Score: ${Math.floor(this.score)}`);
    }
}
