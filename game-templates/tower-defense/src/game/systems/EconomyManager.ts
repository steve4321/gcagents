import { __GAME_CONFIG__ } from '../config';

export class EconomyManager {
  gold: number;

  constructor() {
    this.gold = __GAME_CONFIG__.economy.startGold;
  }

  canAfford(cost: number): boolean {
    return this.gold >= cost;
  }

  spend(cost: number): boolean {
    if (!this.canAfford(cost)) return false;
    this.gold -= cost;
    return true;
  }

  earn(amount: number): void {
    this.gold += amount;
  }
}
