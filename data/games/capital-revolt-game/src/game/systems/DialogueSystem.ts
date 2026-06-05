import * as Phaser from 'phaser';
import { GAME_CONFIG } from '../config';

export class DialogueSystem {
    private scene: Phaser.Scene;
    private textObject!: Phaser.GameObjects.Text;
    private speakerObject!: Phaser.GameObjects.Text;
    private boxGraphics!: Phaser.GameObjects.Graphics;
    private dialogueText = '';
    private typeSpeed = 30;
    private currentCharIndex = 0;
    private isTyping = false;
    private typingTimer?: Phaser.Time.TimerEvent;
    private callback?: () => void;

    constructor(scene: Phaser.Scene) {
        this.scene = scene;
        this.createUI();
    }

    private createUI(): void {
        const w = this.scene.scale.width;
        const h = this.scene.scale.height;
        const font = GAME_CONFIG.fonts.main;

        this.boxGraphics = this.scene.add.graphics();
        this.boxGraphics.fillStyle(0x000000, 0.85);
        this.boxGraphics.fillRoundedRect(15, h - 190, w - 30, 175, 8);
        this.boxGraphics.lineStyle(1, 0x00ff88, 0.4);
        this.boxGraphics.strokeRoundedRect(15, h - 190, w - 30, 175, 8);
        this.boxGraphics.setDepth(50);

        this.speakerObject = this.scene.add.text(30, h - 182, '', {
            fontFamily: font,
            fontSize: '18px',
            fontStyle: 'bold',
            color: '#ffcc00'
        });
        this.speakerObject.setDepth(51);

        this.textObject = this.scene.add.text(30, h - 152, '', {
            fontFamily: font,
            fontSize: '16px',
            color: '#ffffff',
            wordWrap: { width: w - 60 },
            lineSpacing: 4
        });
        this.textObject.setDepth(51);
    }

    show(speaker: string, text: string, callback?: () => void): void {
        this.dialogueText = text;
        this.callback = callback;
        this.currentCharIndex = 0;
        this.isTyping = true;

        const speakerColor = GAME_CONFIG.colors.speakerColors[speaker as keyof typeof GAME_CONFIG.colors.speakerColors] || '#ffcc00';
        this.speakerObject.setText(speaker);
        this.speakerObject.setColor(speakerColor);
        this.textObject.setText('');

        this.typeNextChar();
    }

    private typeNextChar(): void {
        if (this.currentCharIndex >= this.dialogueText.length) {
            this.isTyping = false;
            if (this.callback) {
                this.callback();
            }
            return;
        }

        this.textObject.setText(this.dialogueText.substring(0, this.currentCharIndex + 1));
        this.currentCharIndex++;

        this.typingTimer = this.scene.time.delayedCall(this.typeSpeed, () => {
            this.typeNextChar();
        });
    }

    completeImmediately(): void {
        if (this.typingTimer) {
            this.typingTimer.remove();
            this.typingTimer = undefined;
        }

        this.textObject.setText(this.dialogueText);
        this.currentCharIndex = this.dialogueText.length;
        this.isTyping = false;

        if (this.callback) {
            this.callback();
        }
    }

    isComplete(): boolean {
        return !this.isTyping;
    }

    setSpeed(speed: number): void {
        this.typeSpeed = speed;
    }

    destroy(): void {
        this.completeImmediately();
        if (this.textObject) this.textObject.destroy();
        if (this.speakerObject) this.speakerObject.destroy();
        if (this.boxGraphics) this.boxGraphics.destroy();
    }
}
