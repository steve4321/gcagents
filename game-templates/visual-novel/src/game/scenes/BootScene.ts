import characters from '../data/characters.json';
import dialogue from '../data/dialogue.json';
import branching from '../data/branching.json';

export class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: 'BootScene' });
  }

  create(): void {
    const loaded = {
      characters: Array.isArray(characters?.characters) ? characters.characters.length : 0,
      dialogueLines: Array.isArray(dialogue?.lines) ? dialogue.lines.length : 0,
      branchingNodes: branching?.branching_tree?.nodes ? Object.keys(branching.branching_tree.nodes).length : 0,
    };
    this.scene.start('TitleScene', { loaded });
  }
}
