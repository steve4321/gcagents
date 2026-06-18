import * as Phaser from 'phaser';
import { Projectile, ProjectileData } from '../entities/Projectile';
import { Enemy } from '../entities/Enemy';

export class ProjectilePool {
  private pool: Projectile[] = [];
  private active: Projectile[] = [];
  private scene: Phaser.Scene;

  constructor(scene: Phaser.Scene, preAllocate = 60) {
    this.scene = scene;
    for (let i = 0; i < preAllocate; i++) {
      const proj = new Projectile(scene, -100, -100, 3, 0xf7d51d);
      proj.setVisible(false);
      proj.setActive(false);
      this.pool.push(proj);
    }
  }

  fire(x: number, y: number, target: Enemy, data: ProjectileData): Projectile {
    let proj = this.pool.pop();
    if (!proj) {
      proj = new Projectile(this.scene, -100, -100, 3, 0xf7d51d);
    }
    proj.fire(x, y, target, data);
    if (!this.scene.children.exists(proj)) {
      this.scene.add.existing(proj);
    }
    this.active.push(proj);
    return proj;
  }

  update(delta: number, allEnemies: Enemy[], onKill: (enemy: Enemy) => void): void {
    const stillActive: Projectile[] = [];

    for (const proj of this.active) {
      const hit = proj.update(delta);

      if (hit && proj.targetEnemy) {
        if (proj.isSplash()) {
          const target = proj.targetEnemy;
          for (const enemy of allEnemies) {
            if (enemy.isDead || enemy.reachedEnd) continue;
            const dist = enemy.getDistanceTo(proj.x, proj.y);
            if (dist <= proj.splashRadius) {
              const wasAlive = !enemy.isDead;
              proj.applyHit(enemy);
              if (wasAlive && enemy.isDead) onKill(enemy);
            }
          }
        } else {
          const wasAlive = !proj.targetEnemy.isDead;
          proj.applyHit(proj.targetEnemy);
          if (wasAlive && proj.targetEnemy.isDead) onKill(proj.targetEnemy);
        }
        proj.reset();
        this.pool.push(proj);
      } else if (!proj.isAlive) {
        this.pool.push(proj);
      } else {
        stillActive.push(proj);
      }
    }

    this.active = stillActive;
  }

  getActiveCount(): number {
    return this.active.length;
  }

  clear(): void {
    for (const proj of this.active) {
      proj.reset();
      this.pool.push(proj);
    }
    this.active = [];
  }
}
