import * as Phaser from 'phaser';
import { Enemy } from './Enemy';

export interface ProjectileData {
  damage: number;
  speed: number;
  splashRadius: number;
  slowFactor: number;
  slowDuration: number;
}

export class Projectile extends Phaser.GameObjects.Arc {
  targetEnemy: Enemy | null = null;
  damage = 0;
  speed = 0;
  splashRadius = 0;
  slowFactor = 0;
  slowDuration = 0;
  isAlive = false;

  fire(x: number, y: number, target: Enemy, data: ProjectileData): void {
    this.setPosition(x, y);
    this.targetEnemy = target;
    this.damage = data.damage;
    this.speed = data.speed;
    this.splashRadius = data.splashRadius;
    this.slowFactor = data.slowFactor;
    this.slowDuration = data.slowDuration;
    this.isAlive = true;
    this.setVisible(true);
    this.setActive(true);

    if (this.splashRadius > 0) {
      this.setRadius(6);
      this.setFillStyle(0xe74c3c);
    } else if (this.slowFactor > 0) {
      this.setRadius(4);
      this.setFillStyle(0x3498db);
    } else {
      this.setRadius(3);
      this.setFillStyle(0xf7d51d);
    }
    this.setStrokeStyle(1, 0xffffff, 0.6);
  }

  reset(): void {
    this.isAlive = false;
    this.targetEnemy = null;
    this.setVisible(false);
    this.setActive(false);
  }

  update(delta: number): boolean {
    if (!this.isAlive) return false;

    const target = this.targetEnemy;
    if (!target || target.isDead) {
      this.reset();
      return false;
    }

    const dt = delta / 1000;
    const dx = target.x - this.x;
    const dy = target.y - this.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const moveDist = this.speed * dt;

    if (dist <= moveDist + target.radius) {
      return true;
    }

    this.x += (dx / dist) * moveDist;
    this.y += (dy / dist) * moveDist;
    return false;
  }

  applyHit(enemy: Enemy): void {
    enemy.takeDamage(this.damage);
    if (this.slowFactor > 0 && this.slowDuration > 0) {
      enemy.applySlow(this.slowFactor, this.slowDuration);
    }
  }

  isSplash(): boolean {
    return this.splashRadius > 0;
  }
}
