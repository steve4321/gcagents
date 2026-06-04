import { VN_WIDTH, VN_HEIGHT, DIALOGUE_BOX, NAME_BOX } from '../config';
import { DialogueSystem } from '../systems/DialogueSystem';
import dialogueData from '../data/dialogue.json';
import charactersData from '../data/characters.json';

interface Character {
  name: string;
  sprite_set: string;
  expression_variants: string[];
}

interface DialogueLine {
  id: string;
  scene_id: string;
  speaker: string;
  text: string;
  expression?: string;
}

export class NovelScene extends Phaser.Scene {
  private dialogueSystem!: DialogueSystem;
  private currentLineIndex = 0;
  private visitedScenes: string[] = [];
  private cgsUnlocked: string[] = [];
  private endingsReached: string[] = [];
  private routeProgress: Record<string, number> = {};
  private flags: string[] = [];
  private currentRoute = 'common';

  constructor() {
    super({ key: 'NovelScene' });
  }

  create(): void {
    this.cameras.main.setBackgroundColor('#0a0a14');

    const chars = (charactersData as { characters: Character[] }).characters;
    this.add.text(NAME_BOX.x, NAME_BOX.y, 'Narrator', {
      fontSize: '20px',
      color: '#ffdd88',
      fontFamily: 'serif',
    });

    this.dialogueSystem = new DialogueSystem(this, DIALOGUE_BOX);
    this.dialogueSystem.on('lineComplete', () => this.advance());

    const lines = (dialogueData as { lines: DialogueLine[] }).lines;
    if (lines.length > 0) {
      this.showLine(lines[0]);
    } else {
      this.add.text(VN_WIDTH / 2, VN_HEIGHT / 2, 'No dialogue data found', {
        fontSize: '24px',
        color: '#ff8888',
      }).setOrigin(0.5);
    }

    this.input.on('pointerdown', () => this.dialogueSystem.complete());

    if (window.__TEST__) {
      window.__TEST__.ready = true;
    }

    void chars;
  }

  private showLine(line: DialogueLine): void {
    if (!this.visitedScenes.includes(line.scene_id)) {
      this.visitedScenes.push(line.scene_id);
    }
    const nameText = this.children.getByName('speakerName') as Phaser.GameObjects.Text | null;
    if (nameText) {
      nameText.setText(line.speaker);
    } else {
      this.add.text(NAME_BOX.x, NAME_BOX.y, line.speaker, {
        fontSize: '20px',
        color: '#ffdd88',
        fontFamily: 'serif',
      }).setName('speakerName');
    }
    this.dialogueSystem.show(line.text);
  }

  private advance(): void {
    const lines = (dialogueData as { lines: DialogueLine[] }).lines;
    this.currentLineIndex += 1;
    if (this.currentLineIndex < lines.length) {
      this.showLine(lines[this.currentLineIndex]);
    } else {
      this.endDemo();
    }
  }

  private endDemo(): void {
    this.add.text(VN_WIDTH / 2, VN_HEIGHT / 2, '[End of demo] — Phase 1 skeleton', {
      fontSize: '28px',
      color: '#ffffff',
    }).setOrigin(0.5);
  }

  getTestState(): Record<string, unknown> {
    return {
      currentScene: this.scene.key,
      currentRoute: this.currentRoute,
      stats: {},
      flags: this.flags,
      cgsUnlocked: this.cgsUnlocked,
      routeProgress: this.routeProgress,
      endingReached: this.endingsReached[0] ?? null,
      saveDataValid: false,
      visitedScenes: this.visitedScenes,
      endingsReached: this.endingsReached,
    };
  }
}
