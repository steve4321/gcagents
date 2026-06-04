import { DIALOGUE_BOX } from '../config';

type CompleteCallback = () => void;

export class DialogueSystem {
  private scene: Phaser.Scene;
  private box: Phaser.GameObjects.Rectangle;
  private textObj!: Phaser.GameObjects.Text;
  private fullText = '';
  private displayed = '';
  private typewriterTimer?: Phaser.Time.TimerEvent;
  private completeCb: CompleteCallback = () => {};
  private isComplete = false;
  private readonly charDelayMs = 30;

  constructor(scene: Phaser.Scene, box: { x: number; y: number; width: number; height: number }) {
    this.scene = scene;
    this.box = scene.add.rectangle(box.x, box.y, box.width, box.height, 0x000000, 0.75)
      .setOrigin(0, 0)
      .setStrokeStyle(2, 0xffffff, 0.4);
  }

  on(event: 'lineComplete', cb: CompleteCallback): void {
    if (event === 'lineComplete') this.completeCb = cb;
  }

  show(text: string): void {
    this.fullText = text;
    this.displayed = '';
    this.isComplete = false;

    if (this.textObj) this.textObj.destroy();
    this.textObj = this.scene.add.text(
      DIALOGUE_BOX.x + DIALOGUE_BOX.padding,
      DIALOGUE_BOX.y + DIALOGUE_BOX.padding,
      '',
      { fontSize: '22px', color: '#ffffff', fontFamily: 'serif', wordWrap: { width: DIALOGUE_BOX.width - 2 * DIALOGUE_BOX.padding } },
    );

    this.typewriterTimer?.remove();
    this.typewriterTimer = this.scene.time.addEvent({
      delay: this.charDelayMs,
      callback: this.tickTypewriter,
      callbackScope: this,
      loop: true,
    });
  }

  private tickTypewriter(): void {
    if (this.isComplete) return;
    this.displayed = this.fullText.slice(0, this.displayed.length + 1);
    this.textObj.setText(this.displayed);
    if (this.displayed.length >= this.fullText.length) {
      this.finishLine();
    }
  }

  complete(): void {
    if (this.isComplete) {
      this.completeCb();
      return;
    }
    this.displayed = this.fullText;
    this.textObj.setText(this.displayed);
    this.finishLine();
  }

  private finishLine(): void {
    this.isComplete = true;
    this.typewriterTimer?.remove();
    this.completeCb();
  }
}
