import * as Phaser from 'phaser';
import { BranchingEngine, createBranchingEngine, BranchingNode, Choice } from '../systems/BranchingEngine';
import { StatSystem, createStatSystem } from '../systems/StatSystem';
import { ChoiceSystem, createChoiceSystem } from '../systems/ChoiceSystem';
import { DialogueSystem } from '../systems/DialogueSystem';
import { GAME_CONFIG } from '../config';
import dialogueData from '../data/dialogue.json';
import endingsData from '../data/endings.json';

interface DialogueEntry {
    speaker: string;
    text: string;
    emotion?: string;
}

interface DialogueData {
    [key: string]: DialogueEntry[];
}

interface EndingTrigger {
    route?: string;
    conditions: Record<string, Record<string, number>>;
}

interface Ending {
    name: string;
    key: string;
    epilogue_key: string;
    is_good_ending: boolean;
    description: string;
    trigger: EndingTrigger;
}

interface EndingsData {
    endings: Ending[];
    epilogues: Record<string, { title: string; text: string }>;
}

interface EpilogueData {
    title: string;
    text: string;
}

const dialogueJson = dialogueData as unknown as DialogueData;
const endingsJson = endingsData as unknown as EndingsData;

type SceneState = 'presenting_dialogue' | 'showing_choices' | 'transitioning' | 'ending' | 'game_over';

const SCENE_BG_COLORS: Record<string, { top: number; bottom: number; accent: number }> = {
    office_night: { top: 0x0a0a1a, bottom: 0x050510, accent: 0x0044aa },
    office_day: { top: 0x0d1117, bottom: 0x050510, accent: 0x2266aa },
    office_manager: { top: 0x1a0a0a, bottom: 0x0a0505, accent: 0xaa3333 },
    breakroom: { top: 0x0a0a14, bottom: 0x050508, accent: 0x4466aa },
    hacker_den: { top: 0x001a0a, bottom: 0x000a05, accent: 0x00ff44 },
    union_hall: { top: 0x1a1408, bottom: 0x0a0a04, accent: 0xcc8833 },
    news_office: { top: 0x0f0f14, bottom: 0x050508, accent: 0x5588cc },
    startup: { top: 0x0a141a, bottom: 0x050a0d, accent: 0x33aacc }
};

export class NovelScene extends Phaser.Scene {
    private branchingEngine!: BranchingEngine;
    private statSystem!: StatSystem;
    private choiceSystem!: ChoiceSystem;
    private dialogueSystem!: DialogueSystem;
    private currentState: SceneState = 'presenting_dialogue';
    private dialogueQueue: DialogueEntry[] = [];
    private currentDialogueIndex: number = 0;
    private isTypingComplete: boolean = false;
    private sessionStart: number = 0;
    private endingsReached: Set<string> = new Set();
    private routeProgress: Map<string, number> = new Map();
    private cgsUnlocked: Set<string> = new Set();
    private transitionOverlay!: Phaser.GameObjects.Rectangle;
    private backgroundGraphics!: Phaser.GameObjects.Graphics;
    private statBarGraphics: Map<string, Phaser.GameObjects.Graphics> = new Map();
    private statLabelTexts: Phaser.GameObjects.Text[] = [];
    private statValueTexts: Phaser.GameObjects.Text[] = [];
    private titleText!: Phaser.GameObjects.Text;
    private pauseElements: Phaser.GameObjects.GameObject[] = [];

    static readonly KEY = 'NovelScene';

    constructor() {
        super({ key: NovelScene.KEY });
    }

    create(): void {
        this.sessionStart = Date.now();

        this.createBackground();
        this.createUI();
        this.initializeSystems();
        this.bindInput();
        this.startScene();
        this.setupTestInterface();
    }

    private createBackground(): void {
        const w = this.scale.width;
        const h = this.scale.height;

        this.backgroundGraphics = this.add.graphics();
        this.drawSceneBackground('office_night');

        this.transitionOverlay = this.add.rectangle(w / 2, h / 2, w, h, 0x000000);
        this.transitionOverlay.setAlpha(0);
        this.transitionOverlay.setDepth(200);
    }

    private drawSceneBackground(sceneKey: string): void {
        const w = this.scale.width;
        const h = this.scale.height;
        const colors = SCENE_BG_COLORS[sceneKey] || SCENE_BG_COLORS.office_night;

        this.backgroundGraphics.clear();
        this.backgroundGraphics.fillGradientStyle(colors.top, colors.top, colors.bottom, colors.bottom, 1);
        this.backgroundGraphics.fillRect(0, 0, w, h);

        this.backgroundGraphics.lineStyle(1, colors.accent, 0.1);
        if (sceneKey === 'hacker_den') {
            for (let y = 0; y < h; y += 20) {
                this.backgroundGraphics.beginPath();
                this.backgroundGraphics.moveTo(0, y);
                this.backgroundGraphics.lineTo(w, y);
                this.backgroundGraphics.strokePath();
            }
        } else {
            for (let x = 0; x < w; x += 50) {
                this.backgroundGraphics.beginPath();
                this.backgroundGraphics.moveTo(x, 0);
                this.backgroundGraphics.lineTo(x, h);
                this.backgroundGraphics.strokePath();
            }
            for (let y = 0; y < h; y += 50) {
                this.backgroundGraphics.beginPath();
                this.backgroundGraphics.moveTo(0, y);
                this.backgroundGraphics.lineTo(w, y);
                this.backgroundGraphics.strokePath();
            }
        }
    }

    private createUI(): void {
        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        this.titleText = this.add.text(w / 2, 15, '', {
            fontFamily: font,
            fontSize: '14px',
            color: '#555555'
        }).setOrigin(0.5, 0).setDepth(60);

        const statNames = ['morality', 'economy', 'social_influence', 'mental_health', 'technical_ability'];
        const barX = w - 140;
        let barY = 30;
        const barWidth = 110;
        const barHeight = 10;

        for (const statName of statNames) {
            const def = this.statSystem ? this.statSystem.getStatDisplayInfo(statName) : null;
            const displayName = def ? def.display_name : statName;

            const graphics = this.add.graphics();
            graphics.setDepth(60);
            this.statBarGraphics.set(statName, graphics);

            const label = this.add.text(barX, barY - 15, displayName, {
                fontFamily: font,
                fontSize: '11px',
                color: '#aaaaaa'
            }).setDepth(60);
            this.statLabelTexts.push(label);

            const valueText = this.add.text(barX + barWidth + 5, barY - 3, '50', {
                fontFamily: font,
                fontSize: '10px',
                color: '#cccccc'
            }).setDepth(60);
            this.statValueTexts.push(valueText);

            barY += barHeight + 25;
        }

        const menuBtn = this.add.text(w - 15, 12, '菜单', {
            fontFamily: font,
            fontSize: '13px',
            color: '#666666'
        }).setOrigin(1, 0).setDepth(60).setInteractive({ useHandCursor: true });
        menuBtn.on('pointerdown', () => this.showPauseMenu());
    }

    private initializeSystems(): void {
        this.branchingEngine = createBranchingEngine();
        this.statSystem = createStatSystem();

        const choiceCallbacks = {
            onChoiceSelected: (choice: Choice) => this.handleChoice(choice),
            onChoiceHover: (_choice: Choice | null) => {}
        };

        this.choiceSystem = createChoiceSystem(
            this,
            this.scale.width / 2,
            this.scale.height / 2 + 100,
            this.statSystem,
            choiceCallbacks
        );

        this.dialogueSystem = new DialogueSystem(this);
    }

    private bindInput(): void {
        this.input.keyboard?.on('keydown-SPACE', () => this.handleAdvance());
        this.input.keyboard?.on('keydown-ENTER', () => {
            if (this.currentState === 'showing_choices') {
                this.choiceSystem.handleKeyboardConfirm();
            } else {
                this.handleAdvance();
            }
        });
        this.input.keyboard?.on('keydown-UP', () => this.choiceSystem.handleKeyboardUp());
        this.input.keyboard?.on('keydown-DOWN', () => this.choiceSystem.handleKeyboardDown());
        this.input.keyboard?.on('keydown-ESC', () => {
            if (this.pauseElements.length === 0) this.showPauseMenu();
        });

        this.input.on('pointerdown', () => {
            if (this.currentState === 'presenting_dialogue') {
                this.handleAdvance();
            }
        });
    }

    private startScene(): void {
        const node = this.branchingEngine.getCurrentNode();
        if (node) {
            this.loadNode(node);
        }
    }

    private loadNode(node: BranchingNode): void {
        this.drawSceneBackground(node.scene_key);
        this.titleText.setText(node.title || '');

        if (node.dialogue && node.dialogue.length > 0) {
            this.dialogueQueue = [];
            for (const dialogueKey of node.dialogue) {
                const entries = dialogueJson[dialogueKey];
                if (entries) {
                    this.dialogueQueue.push(...entries);
                }
            }
            this.currentDialogueIndex = 0;
            this.isTypingComplete = false;
            this.currentState = 'presenting_dialogue';
            this.presentCurrentDialogue();
        } else {
            this.showChoicesOrEnding();
        }

        this.updateStatBars();
        this.updateRouteProgress();
    }

    private presentCurrentDialogue(): void {
        if (this.currentDialogueIndex >= this.dialogueQueue.length) {
            this.showChoicesOrEnding();
            return;
        }

        const entry = this.dialogueQueue[this.currentDialogueIndex];
        this.isTypingComplete = false;
        this.currentState = 'presenting_dialogue';

        this.dialogueSystem.show(entry.speaker, entry.text, () => {
            this.isTypingComplete = true;
        });
    }

    private handleAdvance(): void {
        if (this.currentState === 'showing_choices' || this.currentState === 'ending' || this.currentState === 'game_over') return;

        if (this.currentState === 'presenting_dialogue') {
            if (!this.isTypingComplete) {
                this.dialogueSystem.completeImmediately();
                this.isTypingComplete = true;
                return;
            }
            this.currentDialogueIndex++;
            this.presentCurrentDialogue();
        }
    }

    private showChoicesOrEnding(): void {
        const node = this.branchingEngine.getCurrentNode();
        if (!node || node.choices.length === 0) {
            this.checkEnding();
            return;
        }

        this.currentState = 'showing_choices';
        this.choiceSystem.showChoices(node);
        this.choiceSystem.showAnimated();
    }

    private handleChoice(choice: Choice): void {
        this.statSystem.applyDeltas(choice.stat_delta);
        if (choice.unlocks_route) {
            this.cgsUnlocked.add(choice.unlocks_route);
        }

        this.choiceSystem.hideAnimated();

        const nextNode = this.branchingEngine.advance(choice.id);
        this.currentState = 'transitioning';

        this.playTransition(() => {
            if (nextNode) {
                this.loadNode(nextNode);
            } else {
                this.checkEnding();
            }
            this.updateStatBars();
            this.updateRouteProgress();
        });
    }

    private playTransition(onComplete: () => void): void {
        this.tweens.add({
            targets: this.transitionOverlay,
            alpha: 1,
            duration: 300,
            onComplete: () => {
                onComplete();
                this.tweens.add({
                    targets: this.transitionOverlay,
                    alpha: 0,
                    duration: 300
                });
            }
        });
    }

    private updateStatBars(): void {
        const statNames = ['morality', 'economy', 'social_influence', 'mental_health', 'technical_ability'];
        const w = this.scale.width;
        const barX = w - 140;
        let barY = 30;
        const barWidth = 110;
        const barHeight = 10;

        for (let i = 0; i < statNames.length; i++) {
            const statName = statNames[i];
            const graphics = this.statBarGraphics.get(statName);
            if (!graphics) continue;

            const value = this.statSystem.get(statName);
            const def = this.statSystem.getStatDisplayInfo(statName);
            if (!def) continue;

            const pct = Phaser.Math.Clamp((value - def.range[0]) / (def.range[1] - def.range[0]), 0, 1);

            graphics.clear();
            graphics.fillStyle(0x222233);
            graphics.fillRoundedRect(barX, barY, barWidth, barHeight, 2);

            const colorNum = parseInt(def.color.replace('#', ''), 16);
            graphics.fillStyle(colorNum);
            graphics.fillRoundedRect(barX, barY, barWidth * pct, barHeight, 2);

            graphics.lineStyle(1, 0x444455);
            graphics.strokeRoundedRect(barX, barY, barWidth, barHeight, 2);

            if (this.statValueTexts[i]) {
                this.statValueTexts[i].setText(Math.round(value).toString());
            }

            barY += barHeight + 25;
        }
    }

    private updateRouteProgress(): void {
        this.routeProgress = new Map(Object.entries(this.branchingEngine.calculateRouteProgress()));
    }

    private checkEnding(): void {
        const endingKey = this.branchingEngine.getEndingKey();
        if (endingKey) {
            const ending = endingsJson.endings.find(e => e.key === endingKey);
            if (ending) {
                this.triggerEnding(ending);
                return;
            }
        }

        for (const ending of endingsJson.endings) {
            if (ending.trigger.route) {
                const routes = this.branchingEngine.getActiveRoutes();
                if (!routes.has(ending.trigger.route)) continue;
            }
            if (ending.trigger.conditions) {
                if (!this.statSystem.evaluateConditions(ending.trigger.conditions)) continue;
            }
            this.triggerEnding(ending);
            return;
        }

        this.triggerDefaultEnding();
    }

    private triggerDefaultEnding(): void {
        const mentalHealth = this.statSystem.get('mental_health');
        const morality = this.statSystem.get('morality');
        let defaultKey = 'ending_burnout';

        if (mentalHealth <= 20) {
            defaultKey = 'ending_burnout';
        } else if (morality <= 15) {
            defaultKey = 'ending_capitalist';
        } else {
            defaultKey = 'ending_burnout';
        }

        const ending = endingsJson.endings.find(e => e.key === defaultKey);
        if (ending) {
            this.triggerEnding(ending);
        }
    }

    private triggerEnding(ending: Ending): void {
        this.currentState = 'ending';
        this.endingsReached.add(ending.key);

        this.dialogueSystem.destroy();

        const epilogue = endingsJson.epilogues[ending.epilogue_key] as EpilogueData | undefined;
        if (epilogue) {
            this.showEpilogue(ending, epilogue);
        } else {
            this.showGameOver(ending);
        }
    }

    private showEpilogue(ending: Ending, epilogue: EpilogueData): void {
        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        const overlay = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.9).setDepth(150);

        const endTitle = this.add.text(w / 2, h / 2 - 120, ending.is_good_ending ? '胜利' : '游戏结束', {
            fontFamily: font,
            fontSize: '42px',
            fontStyle: 'bold',
            color: ending.is_good_ending ? '#4ade80' : '#ef4444'
        }).setOrigin(0.5).setDepth(151);

        const endName = this.add.text(w / 2, h / 2 - 70, ending.name, {
            fontFamily: font,
            fontSize: '24px',
            color: '#ffffff'
        }).setOrigin(0.5).setDepth(151);

        const epilogueTitle = this.add.text(w / 2, h / 2 - 20, epilogue.title, {
            fontFamily: font,
            fontSize: '18px',
            color: '#ffcc00'
        }).setOrigin(0.5).setDepth(151);

        const epilogueText = this.add.text(w / 2, h / 2 + 30, '', {
            fontFamily: font,
            fontSize: '15px',
            color: '#cccccc',
            wordWrap: { width: 550 },
            align: 'center',
            lineSpacing: 4
        }).setOrigin(0.5).setDepth(151);

        let charIndex = 0;
        const fullText = epilogue.text;
        const typewriter = this.time.addEvent({
            delay: 25,
            callback: () => {
                if (charIndex < fullText.length) {
                    charIndex++;
                    epilogueText.setText(fullText.substring(0, charIndex));
                } else {
                    typewriter.remove();
                    this.time.delayedCall(2000, () => {
                        this.showGameOverButtons(ending);
                    });
                }
            },
            repeat: fullText.length - 1
        });
    }

    private showGameOver(ending: Ending): void {
        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        const overlay = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.9).setDepth(150);

        const title = this.add.text(w / 2, h / 2 - 80, ending.is_good_ending ? '胜利' : '游戏结束', {
            fontFamily: font,
            fontSize: '42px',
            fontStyle: 'bold',
            color: ending.is_good_ending ? '#4ade80' : '#ef4444'
        }).setOrigin(0.5).setDepth(151);

        const desc = this.add.text(w / 2, h / 2 - 20, ending.description, {
            fontFamily: font,
            fontSize: '16px',
            color: '#cccccc',
            wordWrap: { width: 500 },
            align: 'center'
        }).setOrigin(0.5).setDepth(151);

        this.showGameOverButtons(ending);
    }

    private showGameOverButtons(ending: Ending): void {
        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        const restartBtn = this.add.text(w / 2, h / 2 + 100, '重新开始', {
            fontFamily: font,
            fontSize: '20px',
            color: '#00ff88'
        }).setOrigin(0.5).setDepth(152).setInteractive({ useHandCursor: true });

        restartBtn.on('pointerover', () => restartBtn.setColor('#ffffff'));
        restartBtn.on('pointerout', () => restartBtn.setColor('#00ff88'));
        restartBtn.on('pointerdown', () => {
            if (typeof window !== 'undefined' && (window as unknown as Record<string, (() => void)>).__triggerAdBreak) {
                (window as unknown as Record<string, (() => void)>).__triggerAdBreak();
            }
            this.scene.restart();
        });

        const menuBtn = this.add.text(w / 2, h / 2 + 145, '返回主菜单', {
            fontFamily: font,
            fontSize: '16px',
            color: '#888888'
        }).setOrigin(0.5).setDepth(152).setInteractive({ useHandCursor: true });

        menuBtn.on('pointerover', () => menuBtn.setColor('#ffffff'));
        menuBtn.on('pointerout', () => menuBtn.setColor('#888888'));
        menuBtn.on('pointerdown', () => {
            this.scene.start('TitleScene');
        });

        if (ending.is_good_ending) {
            if (typeof window !== 'undefined' && (window as unknown as Record<string, (() => void)>).__triggerHappyTime) {
                (window as unknown as Record<string, (() => void)>).__triggerHappyTime();
            }
        }

        this.currentState = 'game_over';
    }

    private showPauseMenu(): void {
        if (this.currentState === 'ending' || this.currentState === 'game_over') return;
        if (this.pauseElements.length > 0) return;

        const w = this.scale.width;
        const h = this.scale.height;
        const font = GAME_CONFIG.fonts.main;

        const overlay = this.add.rectangle(w / 2, h / 2, w, h, 0x000000, 0.7).setDepth(300);
        const menuBox = this.add.rectangle(w / 2, h / 2, 300, 260, 0x16213e).setStrokeStyle(2, 0x4a4a6a).setDepth(301);

        const menuTitle = this.add.text(w / 2, h / 2 - 95, '暂停', {
            fontFamily: font,
            fontSize: '22px',
            color: '#ffffff'
        }).setOrigin(0.5).setDepth(302);

        const resumeBtn = this.add.text(w / 2, h / 2 - 40, '继续游戏', {
            fontFamily: font,
            fontSize: '20px',
            color: '#00ff88'
        }).setOrigin(0.5).setDepth(302).setInteractive({ useHandCursor: true });
        resumeBtn.on('pointerover', () => resumeBtn.setColor('#ffffff'));
        resumeBtn.on('pointerout', () => resumeBtn.setColor('#00ff88'));
        resumeBtn.on('pointerdown', () => this.closePauseMenu());

        const saveBtn = this.add.text(w / 2, h / 2 + 10, '保存游戏', {
            fontFamily: font,
            fontSize: '18px',
            color: '#cccccc'
        }).setOrigin(0.5).setDepth(302).setInteractive({ useHandCursor: true });
        saveBtn.on('pointerdown', () => {
            this.saveGame();
            saveBtn.setText('已保存！');
            saveBtn.setColor('#4ade80');
        });

        const loadBtn = this.add.text(w / 2, h / 2 + 55, '读取存档', {
            fontFamily: font,
            fontSize: '18px',
            color: '#cccccc'
        }).setOrigin(0.5).setDepth(302).setInteractive({ useHandCursor: true });

        const quitBtn = this.add.text(w / 2, h / 2 + 100, '返回标题', {
            fontFamily: font,
            fontSize: '18px',
            color: '#cc6666'
        }).setOrigin(0.5).setDepth(302).setInteractive({ useHandCursor: true });
        quitBtn.on('pointerover', () => quitBtn.setColor('#ff4444'));
        quitBtn.on('pointerout', () => quitBtn.setColor('#cc6666'));
        quitBtn.on('pointerdown', () => {
            this.closePauseMenu();
            this.scene.start('TitleScene');
        });

        this.pauseElements = [overlay, menuBox, menuTitle, resumeBtn, saveBtn, loadBtn, quitBtn];
    }

    private closePauseMenu(): void {
        for (const elem of this.pauseElements) {
            elem.destroy();
        }
        this.pauseElements = [];
    }

    private saveGame(): void {
        try {
            const saveData = {
                sceneId: this.branchingEngine.getCurrentNodeKey(),
                stats: this.statSystem.getStatObject(),
                flags: {},
                route: '',
                timestamp: Date.now()
            };
            localStorage.setItem('capital_revolt_save', JSON.stringify(saveData));
        } catch (_e) {
            // localStorage unavailable
        }
    }

    private setupTestInterface(): void {
        window.__TEST__ = {
            ready: false,
            state: () => ({
                currentScene: this.branchingEngine.getCurrentNodeKey(),
                currentRoute: Array.from(this.branchingEngine.getActiveRoutes())[0] || 'none',
                stats: this.statSystem.getStatObject(),
                flags: { isPaused: this.currentState === 'ending', hasSave: false, isGoodEnding: false },
                cgsUnlocked: Array.from(this.cgsUnlocked),
                routeProgress: Object.fromEntries(this.routeProgress),
                endingReached: this.endingsReached.size > 0 ? Array.from(this.endingsReached)[0] : null,
                saveDataValid: false,
                visitedScenes: Array.from(this.branchingEngine.getVisitedNodes()),
                endingsReached: Array.from(this.endingsReached),
                sessionTime: (Date.now() - this.sessionStart) / 1000
            })
        };
        window.__TEST__.ready = true;
    }

    update(): void {
        if (this.currentState !== 'ending' && this.currentState !== 'game_over') {
            this.statSystem.tick(0.016);
            this.updateStatBars();
        }
    }
}
