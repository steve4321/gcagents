import * as Phaser from 'phaser';
import { gridToScreen } from '../config';
import { Enemy } from './Enemy';
import { Projectile, ProjectileData } from './Projectile';

export interface TowerData {
  key: string;
  name: string;
  cost: number;
  damage: number;
  range: number;
  fireRate: number;
  projectileSpeed: number;
  projectileType: string;
  splashRadius: number;
  slowFactor: number;
  slowDuration: number;
  color: number;
  radius: number;
  upgrade: {
    cost: number;
    damageMultiplier: number;
    rangeMultiplier: number;
  };
}

export class Tower extends Phaser.GameObjects.Container {
  towerKey = '';
  damage = 0;
  range = 0;
  fireRate = 0;
  projectileSpeed = 0;
  splashRadius = 0;
  slowFactor = 0;
  slowDuration = 0;
  level = 0;

  private bodyShape!: Phaser.GameObjects.Image;
  private rangeCircle!: Phaser.GameObjects.Arc;
  private lastFireTime = 0;
  private towerData!: TowerData;

  init(data: TowerData, col: number, row: number): void {
    this.towerData = data;
    this.towerKey = data.key;
    this.damage = data.damage;
    this.range = data.range;
    this.fireRate = data.fireRate;
    this.projectileSpeed = data.projectileSpeed;
    this.splashRadius = data.splashRadius;
    this.slowFactor = data.slowFactor;
    this.slowDuration = data.slowDuration;
    this.level = 0;
    this.lastFireTime = 0;

    const pos = gridToScreen(col, row);
    this.setPosition(pos.x, pos.y);

    const texKey = `tower_${data.key}`;
    this.bodyShape = this.scene.add.image(0, 0, texKey);
    this.add(this.bodyShape);

    this.rangeCircle = this.scene.add.circle(0, 0, this.range, 0x00ff00, 0);
    this.rangeCircle.setStrokeStyle(2, 0xffffff, 0.3);
    this.rangeCircle.setVisible(false);
    this.add(this.rangeCircle);

    this.setSize(data.radius * 2, data.radius * 2);
  }

  reset(): void {
    this.removeAll(true);
    this.towerKey = '';
    this.level = 0;
    this.setVisible(false);
    this.setActive(false);
  }

  update(time: number, enemies: Enemy[]): { target: Enemy; data: ProjectileData } | null {
    const target = this.findTarget(enemies);
    if (!target) return null;

    if (time - this.lastFireTime < this.fireRate) return null;
    this.lastFireTime = time;

    return {
      target,
      data: {
        damage: this.damage,
        speed: this.projectileSpeed,
        splashRadius: this.splashRadius,
        slowFactor: this.slowFactor,
        slowDuration: this.slowDuration,
      },
    };
  }

  private findTarget(enemies: Enemy[]): Enemy | null {
    let best: Enemy | null = null;
    let bestProgress = -1;

    for (const enemy of enemies) {
      if (enemy.isDead || enemy.reachedEnd) continue;
      const dx = enemy.x - this.x;
      const dy = enemy.y - this.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist <= this.range) {
        if (bestProgress < enemy.waypointProgress) {
          bestProgress = enemy.waypointProgress;
          best = enemy;
        }
      }
    }
    return best;
  }

  canUpgrade(): boolean {
    return this.level === 0;
  }

  getUpgradeCost(): number {
    return this.canUpgrade() ? this.towerData.upgrade.cost : 0;
  }

  upgrade(): void {
    if (!this.canUpgrade()) return;
    this.damage = Math.round(this.damage * this.towerData.upgrade.damageMultiplier);
    this.range = Math.round(this.range * this.towerData.upgrade.rangeMultiplier);
    this.level = 1;

    this.rangeCircle.setRadius(this.range);
    this.bodyShape.setScale(1.15);
    this.bodyShape.setTint(0xffddaa);
  }

  showRange(visible: boolean): void {
    this.rangeCircle.setVisible(visible);
  }

  getGridCol(): number {
    return Math.floor(this.x / 40);
  }

  getGridRow(): number {
    return Math.floor(this.y / 40);
  }
}
