import * as Phaser from 'phaser';
import statsData from '../data/stats.json';

export interface StatDefinition {
    name: string;
    display_name: string;
    description: string;
    range: [number, number];
    default: number;
    decay: number;
    color: string;
    branching_thresholds: Threshold[];
}

export interface Threshold {
    op: string;
    value: number;
    route?: string;
    message?: string;
}

interface StatsConfig {
    stats: StatDefinition[];
}

const config = statsData as unknown as StatsConfig;
const statDefs = new Map<string, StatDefinition>();
for (const stat of config.stats) {
    statDefs.set(stat.name, stat);
}

export class StatSystem {
    private stats: Map<string, number>;
    private statDecays: Map<string, number>;

    constructor() {
        this.stats = new Map();
        this.statDecays = new Map();
        this.initializeStats();
    }

    private initializeStats(): void {
        for (const [, def] of statDefs) {
            this.stats.set(def.name, def.default);
            this.statDecays.set(def.name, def.decay);
        }
    }

    get(statName: string): number {
        return this.stats.get(statName) ?? 0;
    }

    set(statName: string, value: number): void {
        const def = statDefs.get(statName);
        if (!def) return;
        const clampedValue = Phaser.Math.Clamp(value, def.range[0], def.range[1]);
        this.stats.set(statName, clampedValue);
    }

    applyDelta(statName: string, delta: number): number {
        const current = this.get(statName);
        this.set(statName, current + delta);
        return this.get(statName);
    }

    applyDeltas(deltas: Record<string, number>): void {
        for (const [statName, delta] of Object.entries(deltas)) {
            if (statDefs.has(statName)) {
                this.applyDelta(statName, delta);
            }
        }
    }

    getStatObject(): Record<string, number> {
        const obj: Record<string, number> = {};
        for (const [key, value] of this.stats) {
            obj[key] = value;
        }
        return obj;
    }

    evaluateConditions(conditions: Record<string, Record<string, number>>): boolean {
        for (const [statName, requirement] of Object.entries(conditions)) {
            const currentValue = this.get(statName);
            for (const [op, targetValue] of Object.entries(requirement)) {
                let passes = false;
                switch (op) {
                    case '>=': passes = currentValue >= targetValue; break;
                    case '<=': passes = currentValue <= targetValue; break;
                    case '>': passes = currentValue > targetValue; break;
                    case '<': passes = currentValue < targetValue; break;
                    case '==': passes = currentValue === targetValue; break;
                }
                if (!passes) return false;
            }
        }
        return true;
    }

    tick(delta: number): void {
        for (const [statName, decayRate] of this.statDecays) {
            if (decayRate > 0) {
                const current = this.get(statName);
                const def = statDefs.get(statName);
                if (def && current > def.range[0]) {
                    this.set(statName, current - decayRate * delta);
                }
            }
        }
    }

    getStatDisplayInfo(statName: string): StatDefinition | undefined {
        return statDefs.get(statName);
    }

    listAllStats(): StatDefinition[] {
        return Array.from(statDefs.values());
    }

    reset(): void {
        this.stats.clear();
        this.initializeStats();
    }
}

export function createStatSystem(): StatSystem {
    return new StatSystem();
}
