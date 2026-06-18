import * as Phaser from 'phaser';
import { Tower, TowerData } from '../entities/Tower';
import { PathFinder } from './PathFinder';
import { EconomyManager } from './EconomyManager';
import { __GAME_CONFIG__ } from '../config';

export class TowerFactory {
  private scene: Phaser.Scene;
  private pathFinder: PathFinder;
  private economy: EconomyManager;
  private occupiedCells = new Set<string>();
  private towerDataMap = new Map<string, TowerData>();
  private towerPool: Tower[] = [];
  private activeTowers: Tower[] = [];

  constructor(scene: Phaser.Scene, pathFinder: PathFinder, economy: EconomyManager) {
    this.scene = scene;
    this.pathFinder = pathFinder;
    this.economy = economy;
  }

  loadData(towers: TowerData[]): void {
    for (const td of towers) {
      this.towerDataMap.set(td.key, td);
    }
  }

  canPlace(col: number, row: number, towerKey: string): boolean {
    const cellId = `${col},${row}`;
    if (this.occupiedCells.has(cellId)) return false;
    if (this.pathFinder.isOnPath(col, row, __GAME_CONFIG__.grid.cellSize)) return false;
    const td = this.towerDataMap.get(towerKey);
    if (!td) return false;
    if (!this.economy.canAfford(td.cost)) return false;
    return true;
  }

  placeTower(col: number, row: number, towerKey: string): Tower | null {
    if (!this.canPlace(col, row, towerKey)) return null;

    const td = this.towerDataMap.get(towerKey);
    if (!td) return null;

    this.economy.spend(td.cost);
    this.occupiedCells.add(`${col},${row}`);

    let tower = this.towerPool.pop();
    if (!tower) {
      tower = new Tower(this.scene, 0, 0);
    }
    tower.setVisible(true);
    tower.setActive(true);
    tower.init(td, col, row);
    this.activeTowers.push(tower);
    return tower;
  }

  upgradeTower(col: number, row: number): boolean {
    const tower = this.getTowerAt(col, row);
    if (!tower || !tower.canUpgrade()) return false;
    if (!this.economy.canAfford(tower.getUpgradeCost())) return false;
    this.economy.spend(tower.getUpgradeCost());
    tower.upgrade();
    return true;
  }

  getTowerAt(col: number, row: number): Tower | null {
    return this.activeTowers.find(
      (t) => t.getGridCol() === col && t.getGridRow() === row,
    ) ?? null;
  }

  getActiveTowers(): Tower[] {
    return this.activeTowers;
  }

  getTowerTypes(): string[] {
    return Array.from(this.towerDataMap.keys());
  }

  getTowerData(key: string): TowerData | undefined {
    return this.towerDataMap.get(key);
  }
}
