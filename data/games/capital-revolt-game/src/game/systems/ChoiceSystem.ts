import * as Phaser from 'phaser';
import { BranchingNode, Choice } from './BranchingEngine';
import { StatSystem } from './StatSystem';
import { GAME_CONFIG } from '../config';

interface ChoiceCallbacks {
    onChoiceSelected: (choice: Choice) => void;
    onChoiceHover: ((choice: Choice | null) => void) | null;
}

export class ChoiceSystem {
    private scene: Phaser.Scene;
    private choiceContainer: Phaser.GameObjects.Container;
    private choiceButtons: Phaser.GameObjects.Container[] = [];
    private currentChoices: Choice[] = [];
    private selectedIndex: number = 0;
    private callbacks: ChoiceCallbacks;
    private statSystem: StatSystem;
    private statPreviewTexts: Phaser.GameObjects.Text[] = [];
    private isVisible: boolean = false;

    constructor(
        scene: Phaser.Scene,
        x: number,
        y: number,
        statSystem: StatSystem,
        callbacks: ChoiceCallbacks
    ) {
        this.scene = scene;
        this.statSystem = statSystem;
        this.callbacks = callbacks;
        this.choiceContainer = scene.add.container(0, 0);
        this.choiceContainer.setDepth(100);
    }

    showChoices(node: BranchingNode): void {
        this.clearChoices();
        this.currentChoices = node.choices;
        this.selectedIndex = 0;
        this.isVisible = true;

        const w = this.scene.scale.width;
        const h = this.scene.scale.height;
        const font = GAME_CONFIG.fonts.main;
        const startY = h - 200 - (node.choices.length * 55);

        node.choices.forEach((choice, index) => {
            const btnContainer = this.scene.add.container(w / 2, startY + index * 55);

            const btnBg = this.scene.add.rectangle(0, 0, 500, 45, 0x16213e, 0.9);
            btnBg.setStrokeStyle(2, 0x00ff88, 0.6);

            const btnText = this.scene.add.text(0, 0, choice.label, {
                fontFamily: font,
                fontSize: '18px',
                color: '#ffffff'
            }).setOrigin(0.5);

            const statPreview = this.scene.add.text(240, 0, '', {
                fontFamily: font,
                fontSize: '12px',
                color: '#888888'
            }).setOrigin(0, 0.5);

            this.statPreviewTexts.push(statPreview);

            btnContainer.add([btnBg, btnText, statPreview]);
            btnContainer.setAlpha(0);
            btnContainer.setDepth(100);

            btnBg.setInteractive({ useHandCursor: true });
            btnBg.on('pointerover', () => {
                this.selectedIndex = index;
                this.updateSelectionVisual();
                if (this.callbacks.onChoiceHover) {
                    this.callbacks.onChoiceHover(choice);
                }
            });

            btnBg.on('pointerout', () => {
                if (this.callbacks.onChoiceHover) {
                    this.callbacks.onChoiceHover(null);
                }
            });

            btnBg.on('pointerdown', () => {
                this.callbacks.onChoiceSelected(choice);
            });

            this.choiceButtons.push(btnContainer);
            this.choiceContainer.add(btnContainer);
        });

        this.updateSelectionVisual();
    }

    showAnimated(): void {
        this.choiceButtons.forEach((container, index) => {
            this.scene.tweens.add({
                targets: container,
                alpha: 1,
                y: container.y + 10,
                duration: 300,
                delay: index * 80,
                ease: 'Power2'
            });
        });
    }

    hideAnimated(): void {
        this.isVisible = false;
        this.choiceButtons.forEach((container) => {
            this.scene.tweens.add({
                targets: container,
                alpha: 0,
                duration: 200,
                onComplete: () => {
                    container.destroy();
                }
            });
        });
        this.choiceButtons = [];
        this.statPreviewTexts = [];
    }

    getSelectedChoice(): Choice | null {
        if (this.selectedIndex < this.currentChoices.length) {
            return this.currentChoices[this.selectedIndex];
        }
        return null;
    }

    handleKeyboardUp(): void {
        if (!this.isVisible) return;
        this.selectedIndex = Phaser.Math.Wrap(this.selectedIndex - 1, 0, this.currentChoices.length);
        this.updateSelectionVisual();
    }

    handleKeyboardDown(): void {
        if (!this.isVisible) return;
        this.selectedIndex = Phaser.Math.Wrap(this.selectedIndex + 1, 0, this.currentChoices.length);
        this.updateSelectionVisual();
    }

    handleKeyboardConfirm(): void {
        if (!this.isVisible) return;
        const choice = this.getSelectedChoice();
        if (choice) {
            this.callbacks.onChoiceSelected(choice);
        }
    }

    private updateSelectionVisual(): void {
        this.choiceButtons.forEach((container, index) => {
            const bg = container.getAt(0) as Phaser.GameObjects.Rectangle;
            const text = container.getAt(1) as Phaser.GameObjects.Text;
            if (!bg || !text) return;

            if (index === this.selectedIndex) {
                bg.setStrokeStyle(2, 0x00ff88, 1);
                bg.setFillStyle(0x1a3a2e, 0.95);
                text.setColor('#00ff88');
            } else {
                bg.setStrokeStyle(1, 0x00ff88, 0.4);
                bg.setFillStyle(0x16213e, 0.9);
                text.setColor('#cccccc');
            }
        });

        this.updateStatPreviews();
    }

    private updateStatPreviews(): void {
        this.currentChoices.forEach((choice, index) => {
            const previewText = this.statPreviewTexts[index];
            if (!previewText) return;

            const deltas = Object.entries(choice.stat_delta)
                .map(([stat, delta]) => {
                    const def = this.statSystem.getStatDisplayInfo(stat);
                    const name = def ? def.display_name : stat;
                    const sign = delta > 0 ? '+' : '';
                    return `${name}${sign}${delta}`;
                })
                .join(' ');

            previewText.setText(deltas);
        });
    }

    private clearChoices(): void {
        this.choiceButtons.forEach(c => c.destroy());
        this.choiceButtons = [];
        this.currentChoices = [];
        this.statPreviewTexts = [];
    }

    destroy(): void {
        this.clearChoices();
        this.choiceContainer.destroy();
    }
}

export function createChoiceSystem(
    scene: Phaser.Scene,
    x: number,
    y: number,
    statSystem: StatSystem,
    callbacks: ChoiceCallbacks
): ChoiceSystem {
    return new ChoiceSystem(scene, x, y, statSystem, callbacks);
}
