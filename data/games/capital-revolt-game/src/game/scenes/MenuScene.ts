import * as Phaser from 'phaser';
import { GAME_CONFIG } from '../config';

interface SaveData {
    sceneId: string;
    stats: Record<string, number>;
    flags: Record<string, boolean>;
    route: string;
    timestamp: number;
}

export class MenuScene extends Phaser.Scene {
    private buttons: Phaser.GameObjects.Text[] = [];
    private selectedIndex = 0;
    private saveData: SaveData | null = null;
    private buttonBgs: Phaser.GameObjects.Rectangle[] = [];

    constructor() {
        super('MenuScene');
    }

    create(): void {
        this.loadSaveData();
        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        const bg = this.add.graphics();
        bg.fillGradientStyle(0x0a0a1a, 0x0a0a1a, 0x000010, 0x000010, 1);
        bg.fillRect(0, 0, w, h);

        const grid = this.add.graphics();
        grid.lineStyle(1, 0x00ff88, 0.08);
        for (let i = 0; i < 20; i++) {
            const y = (h / 20) * i + 50;
            grid.beginPath();
            grid.moveTo(0, y);
            grid.lineTo(w, y);
            grid.strokePath();
        }

        this.add.text(w / 2, 100, '主菜单', {
            fontFamily: font,
            fontSize: '42px',
            fontStyle: 'bold',
            color: '#00ff88'
        }).setOrigin(0.5);

        const startY = 260;
        const spacing = 70;

        const newGameBtn = this.createMenuButton(w / 2, startY, '新游戏');
        const continueBtn = this.createMenuButton(w / 2, startY + spacing,
            this.saveData ? '继续游戏' : '继续游戏 (无存档)');
        continueBtn.setAlpha(this.saveData ? 1 : 0.4);

        const galleryBtn = this.createMenuButton(w / 2, startY + spacing * 2, '画廊 (未解锁)');
        galleryBtn.setAlpha(0.4);

        this.buttons.push(newGameBtn, continueBtn, galleryBtn);
        this.updateSelection();

        this.input.keyboard?.on('keydown-UP', () => this.moveSelection(-1));
        this.input.keyboard?.on('keydown-DOWN', () => this.moveSelection(1));
        this.input.keyboard?.on('keydown-ENTER', () => this.selectOption());

        this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
            this.handleClick(pointer.x, pointer.y);
        });
    }

    private createMenuButton(x: number, y: number, label: string): Phaser.GameObjects.Text {
        const font = GAME_CONFIG.fonts.main;

        const btnBg = this.add.rectangle(x, y, 280, 45, 0x16213e, 0.8);
        btnBg.setStrokeStyle(1, 0x00ff88, 0.5);
        this.buttonBgs.push(btnBg);

        const btn = this.add.text(x, y, label, {
            fontFamily: font,
            fontSize: '24px',
            color: '#00ff88'
        }).setOrigin(0.5).setInteractive({ useHandCursor: true });

        btn.on('pointerover', () => {
            const idx = this.buttons.indexOf(btn);
            if (idx >= 0) {
                this.selectedIndex = idx;
                this.updateSelection();
            }
        });

        btn.on('pointerdown', () => {
            const idx = this.buttons.indexOf(btn);
            if (idx >= 0) {
                this.selectedIndex = idx;
                this.updateSelection();
                this.selectOption();
            }
        });

        return btn;
    }

    private moveSelection(delta: number): void {
        this.selectedIndex = Phaser.Math.Wrap(
            this.selectedIndex + delta, 0, this.buttons.length
        );
        this.updateSelection();
    }

    private updateSelection(): void {
        this.buttons.forEach((btn, index) => {
            const bg = this.buttonBgs[index];
            if (index === this.selectedIndex) {
                btn.setColor('#ffffff');
                if (bg) bg.setStrokeStyle(2, 0x00ff88, 1);
            } else {
                btn.setColor('#00ff88');
                if (bg) bg.setStrokeStyle(1, 0x00ff88, 0.5);
            }
        });
    }

    private selectOption(): void {
        const btn = this.buttons[this.selectedIndex];
        if (!btn || btn.alpha < 0.5) return;

        if (this.selectedIndex === 0) {
            this.startNewGame();
        } else if (this.selectedIndex === 1 && this.saveData) {
            this.continueGame();
        }
    }

    private handleClick(x: number, y: number): void {
        this.buttons.forEach((btn, index) => {
            const bounds = btn.getBounds();
            if (x >= bounds.left && x <= bounds.right &&
                y >= bounds.top && y <= bounds.bottom &&
                btn.alpha >= 0.5) {
                this.selectedIndex = index;
                this.updateSelection();
                this.selectOption();
            }
        });
    }

    private loadSaveData(): void {
        try {
            const saved = localStorage.getItem('capital_revolt_save');
            if (saved) {
                this.saveData = JSON.parse(saved);
            }
        } catch (_e) {
            this.saveData = null;
        }
    }

    private startNewGame(): void {
        this.registry.set('stats', {
            morality: 50,
            technical_ability: 50,
            social_influence: 50,
            economy: 50,
            mental_health: 50
        });
        this.registry.set('flags', {});
        this.registry.set('currentScene', 'prologue');
        this.registry.set('visitedScenes', []);
        this.registry.set('routeProgress', {});
        this.registry.set('sessionStart', Date.now());

        if (typeof window !== 'undefined' && (window as unknown as Record<string, (() => void)>).__triggerAdBreak) {
            (window as unknown as Record<string, (() => void)>).__triggerAdBreak();
        }

        this.cameras.main.fadeOut(300, 0, 0, 0);
        this.cameras.main.once('camerafadeoutcomplete', () => {
            this.scene.start('NovelScene');
        });
    }

    private continueGame(): void {
        if (this.saveData) {
            this.registry.set('currentScene', this.saveData.sceneId);
            this.registry.set('stats', this.saveData.stats);
            this.registry.set('flags', this.saveData.flags);
            this.registry.set('sessionStart', Date.now());
            this.scene.start('NovelScene');
        }
    }
}
