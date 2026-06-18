import * as Phaser from 'phaser';
import { __GAME_CONFIG__ } from '../config';

export class Base extends Phaser.GameObjects.Container {
  hp: number;
  maxHp: number;

  constructor(scene: Phaser.Scene, x: number, y: number) {
    super(scene, x, y);
    this.maxHp = __GAME_CONFIG__.base.maxHp;
    this.hp = this.maxHp;

    const body = scene.add.rectangle(0, 0, 36, 36, 0x2c3e50);
    body.setStrokeStyle(3, 0xecf0f1);
    this.add(body);

    const roof = scene.add.triangle(0, -14, -18, 6, 18, 6, 0, -14, 0xe74c3c);
    this.add(roof);

    scene.add.existing(this as unknown as Phaser.GameObjects.GameObject);
  }

  takeDamage(amount: number): void {
    this.hp = Math.max(0, this.hp - amount);
  }

  isBaseDestroyed(): boolean {
    return this.hp <= 0;
  }
}
