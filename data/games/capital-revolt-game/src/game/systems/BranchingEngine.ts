import branchingData from '../data/branching.json';

export interface BranchingNode {
    scene_key: string;
    title?: string;
    dialogue: string[];
    choices: Choice[];
}

export interface Choice {
    id: string;
    label: string;
    next_node: string;
    stat_delta: Record<string, number>;
    unlocks_route?: string;
}

export interface BranchingEdge {
    from: string;
    to: string;
    choice_id: string;
}

interface BranchingGraph {
    root: string;
    nodes: Record<string, BranchingNode>;
    edges: BranchingEdge[];
    routes: Record<string, string[]>;
}

const graph = branchingData as unknown as BranchingGraph;

export class BranchingEngine {
    private currentNodeKey: string;
    private visitedNodes: Set<string>;
    private unlockedRoutes: Set<string>;
    private activeRoutes: Set<string>;
    private choiceHistory: string[];

    constructor() {
        this.currentNodeKey = graph.root;
        this.visitedNodes = new Set();
        this.unlockedRoutes = new Set();
        this.activeRoutes = new Set();
        this.choiceHistory = [];
    }

    getCurrentNode(): BranchingNode | undefined {
        return graph.nodes[this.currentNodeKey];
    }

    getCurrentNodeKey(): string {
        return this.currentNodeKey;
    }

    advance(choiceId: string): BranchingNode | null {
        const currentNode = this.getCurrentNode();
        if (!currentNode) return null;

        const chosenChoice = currentNode.choices.find(c => c.id === choiceId);
        if (!chosenChoice) {
            console.error(`Choice ${choiceId} not found in node ${this.currentNodeKey}`);
            return null;
        }

        this.choiceHistory.push(choiceId);
        const nextNodeKey = chosenChoice.next_node;

        if (!graph.nodes[nextNodeKey]) {
            console.error(`Next node ${nextNodeKey} not found`);
            return null;
        }

        if (chosenChoice.unlocks_route) {
            this.unlockedRoutes.add(chosenChoice.unlocks_route);
            this.activeRoutes.add(chosenChoice.unlocks_route);
        }

        this.currentNodeKey = nextNodeKey;
        this.visitedNodes.add(this.currentNodeKey);
        return graph.nodes[this.currentNodeKey];
    }

    getVisitedNodes(): Set<string> {
        return this.visitedNodes;
    }

    getUnlockedRoutes(): Set<string> {
        return this.unlockedRoutes;
    }

    getActiveRoutes(): Set<string> {
        return this.activeRoutes;
    }

    getChoiceHistory(): string[] {
        return [...this.choiceHistory];
    }

    isEndNode(nodeKey?: string): boolean {
        const key = nodeKey || this.currentNodeKey;
        const node = graph.nodes[key];
        if (!node) return false;
        return node.choices.length === 0;
    }

    getEndingKey(): string | null {
        if (this.isEndNode()) {
            return this.currentNodeKey;
        }
        return null;
    }

    calculateRouteProgress(): Record<string, number> {
        const progress: Record<string, number> = {};
        for (const routeName of this.activeRoutes) {
            const routeNodes = graph.routes[routeName];
            if (!routeNodes) continue;
            let visitedInRoute = 0;
            for (const nodeKey of routeNodes) {
                if (this.visitedNodes.has(nodeKey)) visitedInRoute++;
            }
            progress[routeName] = (visitedInRoute / routeNodes.length) * 100;
        }
        return progress;
    }

    reset(): void {
        this.currentNodeKey = graph.root;
        this.visitedNodes.clear();
        this.unlockedRoutes.clear();
        this.activeRoutes.clear();
        this.choiceHistory = [];
    }
}

export function createBranchingEngine(): BranchingEngine {
    return new BranchingEngine();
}
