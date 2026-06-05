import * as Phaser from 'phaser';

export class BootScene extends Phaser.Scene {
    private progressBar!: Phaser.GameObjects.Graphics;
    private progressBox!: Phaser.GameObjects.Graphics;
    private loadingText!: Phaser.GameObjects.Text;

    constructor() {
        super('BootScene');
    }

    preload(): void {
        const width = this.cameras.main.width;
        const height = this.cameras.main.height;

        this.progressBox = this.add.graphics();
        this.progressBox.fillStyle(0x222222, 0.8);
        this.progressBox.fillRect(width / 2 - 160, height / 2 - 25, 320, 50);

        this.progressBar = this.add.graphics();

        this.loadingText = this.add.text(width / 2, height / 2 - 50, '加载中...', {
            fontFamily: "'Noto Sans SC', 'Microsoft YaHei', sans-serif",
            fontSize: '20px',
            color: '#ffffff'
        }).setOrigin(0.5);

        this.load.on('progress', (value: number) => {
            this.progressBar.clear();
            this.progressBar.fillStyle(0x00ff88, 1);
            this.progressBar.fillRect(width / 2 - 150, height / 2 - 15, 300 * value, 30);
        });

        this.load.on('complete', () => {
            this.progressBar.destroy();
            this.progressBox.destroy();
            this.loadingText.destroy();
        });

        this.load.json('characters', '/assets/data/characters.json');
        this.load.json('dialogue', '/assets/data/dialogue.json');
        this.load.json('branching', '/assets/data/branching.json');
        this.load.json('endings', '/assets/data/endings.json');
        this.load.json('stats', '/assets/data/stats.json');
    }

    create(): void {
        try {
            const charactersData = this.cache.json.get('characters');
            const dialogueData = this.cache.json.get('dialogue');
            const branchingData = this.cache.json.get('branching');
            const endingsData = this.cache.json.get('endings');
            const statsData = this.cache.json.get('stats');

            if (charactersData) {
                this.registry.set('characters', charactersData.characters);
            }
            if (dialogueData) {
                this.registry.set('dialogue', dialogueData);
            }
            if (branchingData) {
                this.registry.set('branching', branchingData);
            }
            if (endingsData) {
                this.registry.set('endings', endingsData);
            }
            if (statsData) {
                this.registry.set('stats', statsData);
            }
        } catch (e) {
            console.warn('Could not load JSON data:', e);
        }

        this.registry.set('currentScene', 'prologue');
        this.registry.set('stats', {
            morality: 50,
            technical_ability: 50,
            social_influence: 50,
            economy: 50,
            mental_health: 50
        });
        this.registry.set('flags', {});
        this.registry.set('cgsUnlocked', [] as string[]);
        this.registry.set('routeProgress', {} as Record<string, number>);
        this.registry.set('visitedScenes', [] as string[]);
        this.registry.set('endingsReached', [] as string[]);

        this.scene.start('TitleScene');
    }
}
