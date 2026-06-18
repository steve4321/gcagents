import * as Phaser from 'phaser';
import { Enemy, EnemyData, Waypoint } from '../entities/Enemy';

export interface WaveGroup {
  type: string;
  count: number;
}

export interface WaveConfig {
  wave: number;
  enemies: WaveGroup[];
  spawnInterval: number;
}

export class WaveManager {
  private scene: Phaser.Scene;
  private waves: WaveConfig[];
  private enemyDataMap = new Map<string, EnemyData>();
  private waypoints: Waypoint[];
  private enemyPool: Enemy[] = [];
  private activeEnemies: Enemy[] = [];

  currentWave = 0;
  isWaveActive = false;
  private spawnQueue: { type: string; delay: number }[] = [];
  private spawnTimer = 0;
  private nextSpawnIndex = 0;

  constructor(scene: Phaser.Scene, waves: WaveConfig[], waypoints: Waypoint[]) {
    this.scene = scene;
    this.waves = waves;
    this.waypoints = waypoints;
  }

  loadData(enemies: EnemyData[]): void {
    for (const ed of enemies) {
      this.enemyDataMap.set(ed.key, ed);
    }
  }

  startNextWave(): boolean {
    if (this.currentWave >= this.waves.length) return false;
    if (this.isWaveActive) return false;

    this.currentWave++;
    this.isWaveActive = true;

    const waveConfig = this.waves[this.currentWave - 1];
    this.spawnQueue = [];
    for (const group of waveConfig.enemies) {
      for (let i = 0; i < group.count; i++) {
        this.spawnQueue.push({ type: group.type, delay: waveConfig.spawnInterval });
      }
    }
    this.nextSpawnIndex = 0;
    this.spawnTimer = 0;

    return true;
  }

  update(delta: number): void {
    if (!this.isWaveActive) return;

    this.spawnTimer -= delta;

    while (this.spawnTimer <= 0 && this.nextSpawnIndex < this.spawnQueue.length) {
      const item = this.spawnQueue[this.nextSpawnIndex];
      this.spawnEnemy(item.type);
      this.nextSpawnIndex++;
      this.spawnTimer += item.delay;
    }

    if (this.nextSpawnIndex >= this.spawnQueue.length) {
      const allDone = this.activeEnemies.every(
        (e) => e.isDead || e.reachedEnd,
      );
      if (allDone) {
        this.isWaveActive = false;
      }
    }
  }

  private spawnEnemy(type: string): void {
    const ed = this.enemyDataMap.get(type);
    if (!ed) return;

    let enemy = this.enemyPool.pop();
    if (!enemy) {
      enemy = new Enemy(this.scene, 0, 0);
    }
    enemy.init(ed, this.waypoints);
    if (!this.scene.children.exists(enemy as unknown as Phaser.GameObjects.GameObject)) {
      this.scene.add.existing(enemy as unknown as Phaser.GameObjects.GameObject);
    }
    this.activeEnemies.push(enemy);
  }

  removeDeadEnemies(): Enemy[] {
    const removed: Enemy[] = [];
    const survivors: Enemy[] = [];

    for (const enemy of this.activeEnemies) {
      if (enemy.isDead || enemy.reachedEnd) {
        enemy.reset();
        this.enemyPool.push(enemy);
        removed.push(enemy);
      } else {
        survivors.push(enemy);
      }
    }

    this.activeEnemies = survivors;
    return removed;
  }

  getActiveEnemies(): Enemy[] {
    return this.activeEnemies;
  }

  getEnemiesAlive(): number {
    return this.activeEnemies.filter((e) => !e.isDead && !e.reachedEnd).length;
  }

  getTotalWaves(): number {
    return this.waves.length;
  }

  isAllWavesComplete(): boolean {
    return this.currentWave >= this.waves.length && !this.isWaveActive;
  }
}
