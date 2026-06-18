import * as Phaser from 'phaser';
import { __GAME_CONFIG__, gridToScreen, screenToGrid, isValidCell } from '../config';
import { Base } from '../entities/Base';
import { Enemy } from '../entities/Enemy';
import { Tower, TowerData } from '../entities/Tower';
import { ProjectileData } from '../entities/Projectile';
import { PathFinder } from '../systems/PathFinder';
import { EconomyManager } from '../systems/EconomyManager';
import { ProjectilePool } from '../systems/ProjectilePool';
import { TowerFactory } from '../systems/TowerFactory';
import { WaveManager, WaveConfig } from '../systems/WaveManager';
import { Waypoint } from '../entities/Enemy';

import wavesData from '../data/waves.json';
import enemiesData from '../data/enemies.json';
import towersData from '../data/towers.json';
import pathData from '../data/path.json';

export class GameScene extends Phaser.Scene {
  private base!: Base;
  private pathFinder!: PathFinder;
  private economy!: EconomyManager;
  private projectilePool!: ProjectilePool;
  private towerFactory!: TowerFactory;
  private waveManager!: WaveManager;

  private selectedTowerType: string | null = null;
  private placementPreview: Phaser.GameObjects.Container | null = null;
  private selectedTower: Tower | null = null;

  private goldText!: Phaser.GameObjects.Text;
  private hpText!: Phaser.GameObjects.Text;
  private waveText!: Phaser.GameObjects.Text;
  private startWaveBtn!: Phaser.GameObjects.Text;
  private towerButtons: Map<string, Phaser.GameObjects.Text> = new Map();

  isGameOver = false;
  isVictory = false;

  constructor() {
    super({ key: 'GameScene' });
  }

  create(): void {
    this.isGameOver = false;
    this.isVictory = false;
    this.selectedTowerType = null;
    this.selectedTower = null;

    this.drawBackground();
    this.initSystems();
    this.drawPath();
    this.createHUD();
    this.createTowerMenu();
    this.setupInput();
  }

  private drawBackground(): void {
    const { width, height } = __GAME_CONFIG__.canvas;
    this.add.rectangle(0, 0, width, height, 0x162416).setOrigin(0);

    const { cellSize, cols, rows } = __GAME_CONFIG__.grid;
    const buildColor = __GAME_CONFIG__.buildable.color;
    const buildAlpha = __GAME_CONFIG__.buildable.alpha;

    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < rows; r++) {
        const x = c * cellSize;
        const y = r * cellSize;
        if ((c + r) % 2 === 0) {
          this.add.rectangle(x, y, cellSize, cellSize, 0x1a2e1a).setOrigin(0);
        } else {
          this.add.rectangle(x, y, cellSize, cellSize, 0x162416).setOrigin(0);
        }
      }
    }
  }

  private initSystems(): void {
    const waypoints: Waypoint[] = pathData.waypoints;
    this.pathFinder = new PathFinder(waypoints);
    this.economy = new EconomyManager();
    this.projectilePool = new ProjectilePool(this);

    this.towerFactory = new TowerFactory(this, this.pathFinder, this.economy);
    this.towerFactory.loadData(towersData.towers as TowerData[]);

    this.waveManager = new WaveManager(this, wavesData.waves as WaveConfig[], waypoints);
    this.waveManager.loadData(enemiesData.enemies);

    const end = this.pathFinder.getEnd();
    this.base = new Base(this, end.x - 30, end.y);
  }

  private drawPath(): void {
    const waypoints = pathData.waypoints;
    const pathColor = __GAME_CONFIG__.path.color;
    const pathWidth = __GAME_CONFIG__.path.width;

    const gfx = this.add.graphics();
    gfx.lineStyle(pathWidth, pathColor, 1);
    gfx.beginPath();
    gfx.moveTo(waypoints[0].x, waypoints[0].y);
    for (let i = 1; i < waypoints.length; i++) {
      gfx.lineTo(waypoints[i].x, waypoints[i].y);
    }
    gfx.strokePath();

    for (const wp of waypoints) {
      this.add.circle(wp.x, wp.y, pathWidth / 2 - 2, pathColor);
    }
  }

  private createHUD(): void {
    const hud = __GAME_CONFIG__.hud;

    this.goldText = this.add.text(hud.gold.x, hud.gold.y, '', {
      fontFamily: hud.fontFamily,
      fontSize: `${hud.fontSize}px`,
      color: hud.color,
    });

    this.hpText = this.add.text(hud.hp.x, hud.hp.y, '', {
      fontFamily: hud.fontFamily,
      fontSize: `${hud.fontSize}px`,
      color: hud.color,
    });

    this.waveText = this.add.text(hud.wave.x, hud.wave.y, '', {
      fontFamily: hud.fontFamily,
      fontSize: `${hud.fontSize}px`,
      color: hud.color,
    });

    this.startWaveBtn = this.add.text(350, 8, 'START WAVE', {
      fontFamily: hud.fontFamily,
      fontSize: '20px',
      color: '#ffffff',
      fontStyle: 'bold',
      backgroundColor: '#e67e22',
      padding: { x: 20, y: 8 },
    });

    this.startWaveBtn.setInteractive({ useHandCursor: true });
    this.startWaveBtn.on('pointerover', () => this.startWaveBtn.setStyle({ backgroundColor: '#f39c12' }));
    this.startWaveBtn.on('pointerout', () => this.startWaveBtn.setStyle({ backgroundColor: '#e67e22' }));
    this.startWaveBtn.on('pointerdown', () => {
      this.startNextWave();
    });

    this.updateHUD();
  }

  private createTowerMenu(): void {
    const types = this.towerFactory.getTowerTypes();
    const menuY = __GAME_CONFIG__.hud.towerMenu.y;
    const btnWidth = 150;
    const startX = (__GAME_CONFIG__.canvas.width - types.length * btnWidth) / 2;

    for (let i = 0; i < types.length; i++) {
      const key = types[i];
      const td = this.towerFactory.getTowerData(key);
      if (!td) continue;

      const btn = this.add.text(startX + i * btnWidth, menuY, `${td.name}\n$${td.cost}`, {
        fontFamily: 'Arial',
        fontSize: '14px',
        color: '#ffffff',
        backgroundColor: `#${td.color.toString(16).padStart(6, '0')}`,
        padding: { x: 12, y: 8 },
        align: 'center',
      });

      btn.setInteractive({ useHandCursor: true });
      btn.on('pointerover', () => btn.setStyle({ fontSize: '15px' }));
      btn.on('pointerout', () => {
        btn.setStyle({ fontSize: '14px' });
        if (this.selectedTowerType !== key) {
          btn.setBackgroundColor(`#${td.color.toString(16).padStart(6, '0')}`);
        }
      });
      btn.on('pointerdown', () => {
        this.selectTowerType(key);
      });

      this.towerButtons.set(key, btn);
    }
  }

  private selectTowerType(key: string): void {
    if (this.selectedTowerType === key) {
      this.selectedTowerType = null;
    } else {
      this.selectedTowerType = key;
    }

    for (const [btnKey, btn] of this.towerButtons) {
      const td = this.towerFactory.getTowerData(btnKey);
      if (!td) continue;
      if (btnKey === this.selectedTowerType) {
        btn.setBackgroundColor('#f1c40f');
      } else {
        btn.setBackgroundColor(`#${td.color.toString(16).padStart(6, '0')}`);
      }
    }

    if (this.selectedTower) {
      this.selectedTower.showRange(false);
      this.selectedTower = null;
    }
  }

  private setupInput(): void {
    this.input.on('pointermove', (pointer: Phaser.Input.Pointer) => {
      this.updatePlacementPreview(pointer);
    });

    this.input.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
      const { col, row } = screenToGrid(pointer.x, pointer.y);
      if (!isValidCell(col, row)) return;

      if (this.selectedTowerType) {
        this.placeTower(col, row, this.selectedTowerType);
      } else {
        this.handleTowerSelect(col, row);
      }
    });
  }

  private updatePlacementPreview(pointer: Phaser.Input.Pointer): void {
    if (!this.selectedTowerType) {
      if (this.placementPreview) {
        this.placementPreview.setVisible(false);
      }
      return;
    }

    const { col, row } = screenToGrid(pointer.x, pointer.y);
    if (!isValidCell(col, row)) {
      if (this.placementPreview) this.placementPreview.setVisible(false);
      return;
    }

    const td = this.towerFactory.getTowerData(this.selectedTowerType);
    if (!td) return;

    if (!this.placementPreview) {
      const circle = this.add.circle(0, 0, td.range, 0x00ff00, 0.1);
      circle.setStrokeStyle(2, 0x00ff00, 0.4);
      const texKey = `tower_${td.key}`;
      const img = this.add.image(0, 0, texKey).setAlpha(0.5);
      this.placementPreview = this.add.container(0, 0, [circle, img]);
    }

    const pos = gridToScreen(col, row);
    this.placementPreview.setPosition(pos.x, pos.y);
    this.placementPreview.setVisible(true);

    const canPlace = this.towerFactory.canPlace(col, row, this.selectedTowerType);
    this.placementPreview.setVisible(canPlace);
  }

  placeTower(col: number, row: number, towerType: string): boolean {
    if (!this.towerFactory.canPlace(col, row, towerType)) return false;
    const tower = this.towerFactory.placeTower(col, row, towerType);
    if (!tower) return false;
    this.updateHUD();
    return true;
  }

  upgradeTower(col: number, row: number): boolean {
    const result = this.towerFactory.upgradeTower(col, row);
    if (result) this.updateHUD();
    return result;
  }

  startNextWave(): boolean {
    const started = this.waveManager.startNextWave();
    if (started) {
      this.startWaveBtn.setVisible(false);
      this.updateHUD();
    }
    return started;
  }

  getGold(): number {
    return this.economy.gold;
  }

  getBaseHealth(): number {
    return this.base.hp;
  }

  getCurrentWave(): number {
    return this.waveManager.currentWave;
  }

  isWaveInProgress(): boolean {
    return this.waveManager.isWaveActive;
  }

  getTotalWaves(): number {
    return this.waveManager.getTotalWaves();
  }

  getEnemiesAlive(): number {
    return this.waveManager.getEnemiesAlive();
  }

  getTowersPlaced(): number {
    return this.towerFactory.getActiveTowers().length;
  }

  getEnemyPositions(): Array<{ x: number; y: number; hp: number; maxHp: number }> {
    return this.waveManager.getActiveEnemies()
      .filter((e) => !e.isDead && !e.reachedEnd)
      .map((e) => ({ x: Math.round(e.x), y: Math.round(e.y), hp: e.hp, maxHp: e.maxHp }));
  }

  private handleTowerSelect(col: number, row: number): void {
    if (this.selectedTower) {
      this.selectedTower.showRange(false);
      this.selectedTower = null;
    }

    const tower = this.towerFactory.getTowerAt(col, row);
    if (tower) {
      this.selectedTower = tower;
      tower.showRange(true);
    }
  }

  private updateHUD(): void {
    this.goldText.setText(`Gold: ${this.economy.gold}`);
    this.hpText.setText(`Base HP: ${this.base.hp}/${this.base.maxHp}`);
    this.waveText.setText(`Wave: ${this.waveManager.currentWave}/${this.waveManager.getTotalWaves()}`);

    if (!this.waveManager.isWaveActive && !this.waveManager.isAllWavesComplete() && !this.isGameOver) {
      this.startWaveBtn.setVisible(true);
    }
  }

  update(time: number, delta: number): void {
    if (this.isGameOver) return;

    this.waveManager.update(delta);

    const enemies = this.waveManager.getActiveEnemies();
    for (const enemy of enemies) {
      enemy.update(delta, pathData.waypoints);
    }

    for (const tower of this.towerFactory.getActiveTowers()) {
      const result = tower.update(time, enemies);
      if (result) {
        this.projectilePool.fire(tower.x, tower.y, result.target, result.data);
      }
    }

    this.projectilePool.update(delta, enemies, (enemy) => {
      this.onEnemyKilled(enemy);
    });

    const removed = this.waveManager.removeDeadEnemies();
    for (const enemy of removed) {
      if (enemy.reachedEnd) {
        this.base.takeDamage(enemy.baseDamage);
      }
    }

    this.updateHUD();

    if (this.base.isBaseDestroyed()) {
      this.endGame(false);
    } else if (this.waveManager.isAllWavesComplete()) {
      this.endGame(true);
    }
  }

  private onEnemyKilled(enemy: Enemy): void {
    this.economy.earn(enemy.goldReward);
  }

  private endGame(victory: boolean): void {
    this.isGameOver = true;
    this.isVictory = victory;
    this.projectilePool.clear();

    this.time.delayedCall(500, () => {
      this.scene.start('GameOverScene', { isVictory: victory });
    });
  }
}
