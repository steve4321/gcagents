// Puzzle Match - Match-3 game with 8x8 grid of colored gems
// Click a gem to select, click an adjacent gem to swap
// Matches of 3+ clear and new gems fall from above

const GRID_SIZE = 8;
const GEM_COLORS = [0xff4444, 0x4488ff, 0x44ff44, 0xffff44, 0xcc44ff]; // red, blue, green, yellow, purple
const GEM_COLOR_NAMES = ['red', 'blue', 'green', 'yellow', 'purple'];
const GAME_DURATION = 60; // seconds

interface GemCell {
    row: number;
    col: number;
    colorIndex: number;
    sprite: Phaser.GameObjects.Arc | null;
}

export class GameScene extends Phaser.Scene {
    score = 0;
    timeLeft = GAME_DURATION;
    moves = 0;

    private grid: GemCell[][] = [];
    private cellSize = 55;
    private gridOffsetX = 0;
    private gridOffsetY = 0;
    private selectedGem: { row: number; col: number } | null = null;
    private scoreText!: Phaser.GameObjects.Text;
    private timerText!: Phaser.GameObjects.Text;
    private timerBar!: Phaser.GameObjects.Graphics;
    private isProcessing = false;
    private gameOver = false;

    constructor() {
        super({ key: 'GameScene' });
    }

    create(): void {
        const { width, height } = this.scale;

        // Center the grid
        this.gridOffsetX = (width - GRID_SIZE * this.cellSize) / 2;
        this.gridOffsetY = (height - GRID_SIZE * this.cellSize) / 2 + 20;

        // Score display
        this.scoreText = this.add.text(width / 2, 20, 'Score: 0', {
            fontSize: '24px',
            color: '#ffffff',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        // Timer text
        this.timerText = this.add.text(width - 80, 20, `${this.timeLeft}s`, {
            fontSize: '24px',
            color: '#ff8844',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        // Timer bar background
        this.add.graphics()
            .fillStyle(0x333333, 1)
            .fillRect(20, 50, width - 40, 8);

        // Timer bar foreground
        this.timerBar = this.add.graphics();

        // Initialize grid with no initial matches
        this._initGrid();

        // Click handler
        this.input.on('pointerdown', (_pointer: Phaser.Input.Pointer, gameObjects: Phaser.GameObjects.GameObject[]) => {
            if (this.isProcessing || this.gameOver) return;
            const clicked = gameObjects[0] as Phaser.GameObjects.Arc;
            if (!clicked) return;

            const cell = this._getCellBySprite(clicked);
            if (!cell) return;

            this._handleGemClick(cell.row, cell.col);
        });

        (window as any).__TEST__!.ready = true;
    }

    update(_time: number, delta: number): void {
        if (this.gameOver) return;

        this.timeLeft -= delta / 1000;
        if (this.timeLeft <= 0) {
            this.timeLeft = 0;
            this.gameOver = true;
            this.registry.set('finalScore', this.score);
            this.scene.start('GameOverScene');
            return;
        }

        // Update timer display
        this.timerText.setText(`${Math.ceil(this.timeLeft)}s`);

        // Update timer bar
        const { width } = this.scale;
        this.timerBar.clear();
        const pct = this.timeLeft / GAME_DURATION;
        const barColor = pct > 0.3 ? 0x00ff88 : pct > 0.1 ? 0xffaa00 : 0xff4444;
        this.timerBar.fillStyle(barColor, 1);
        this.timerBar.fillRect(20, 50, (width - 40) * pct, 8);
    }

    /** Initialize grid ensuring no starting matches */
    private _initGrid(): void {
        this.grid = [];
        for (let row = 0; row < GRID_SIZE; row++) {
            this.grid[row] = [];
            for (let col = 0; col < GRID_SIZE; col++) {
                // Pick a color that doesn't create an immediate match
                let colorIndex: number;
                do {
                    colorIndex = Phaser.Math.Between(0, GEM_COLORS.length - 1);
                } while (this._wouldMatch(row, col, colorIndex));

                this._createGem(row, col, colorIndex);
            }
        }
    }

    /** Check if placing colorIndex at (row, col) creates a 3+ match */
    private _wouldMatch(row: number, col: number, colorIndex: number): boolean {
        // Check horizontal (2 left same color)
        if (col >= 2
            && this.grid[row][col - 1]?.colorIndex === colorIndex
            && this.grid[row][col - 2]?.colorIndex === colorIndex) {
            return true;
        }
        // Check vertical (2 above same color)
        if (row >= 2
            && this.grid[row - 1]?.[col]?.colorIndex === colorIndex
            && this.grid[row - 2]?.[col]?.colorIndex === colorIndex) {
            return true;
        }
        return false;
    }

    /** Create a gem sprite at grid position */
    private _createGem(row: number, col: number, colorIndex: number): GemCell {
        const x = this.gridOffsetX + col * this.cellSize + this.cellSize / 2;
        const y = this.gridOffsetY + row * this.cellSize + this.cellSize / 2;

        const sprite = this.add.circle(x, y, this.cellSize / 2 - 4, GEM_COLORS[colorIndex]);
        sprite.setStrokeStyle(2, 0xffffff, 0.3);
        sprite.setInteractive();

        const cell: GemCell = { row, col, colorIndex, sprite };
        this.grid[row][col] = cell;
        return cell;
    }

    /** Handle clicking a gem */
    private _handleGemClick(row: number, col: number): void {
        if (!this.grid[row]?.[col]) return;

        if (this.selectedGem === null) {
            // First selection
            this.selectedGem = { row, col };
            this._highlightGem(row, col, true);
        } else if (this.selectedGem.row === row && this.selectedGem.col === col) {
            // Deselect
            this._highlightGem(row, col, false);
            this.selectedGem = null;
        } else if (this._isAdjacent(this.selectedGem, { row, col })) {
            // Swap attempt
            this._highlightGem(this.selectedGem.row, this.selectedGem.col, false);
            this._trySwap(this.selectedGem.row, this.selectedGem.col, row, col);
            this.selectedGem = null;
        } else {
            // Select new gem instead
            this._highlightGem(this.selectedGem.row, this.selectedGem.col, false);
            this.selectedGem = { row, col };
            this._highlightGem(row, col, true);
        }
    }

    /** Highlight/unhighlight a gem */
    private _highlightGem(row: number, col: number, highlight: boolean): void {
        const cell = this.grid[row]?.[col];
        if (!cell?.sprite) return;
        cell.sprite.setStrokeStyle(2, highlight ? 0xffff00 : 0xffffff, highlight ? 1 : 0.3);
        if (highlight) {
            this.tweens.add({
                targets: cell.sprite,
                scaleX: 1.15,
                scaleY: 1.15,
                duration: 150,
                ease: 'Power2',
            });
        } else {
            this.tweens.add({
                targets: cell.sprite,
                scaleX: 1,
                scaleY: 1,
                duration: 150,
                ease: 'Power2',
            });
        }
    }

    /** Check if two positions are adjacent (horizontally or vertically) */
    private _isAdjacent(a: { row: number; col: number }, b: { row: number; col: number }): boolean {
        return (Math.abs(a.row - b.row) + Math.abs(a.col - b.col)) === 1;
    }

    /** Try swapping two gems; revert if no match */
    private _trySwap(row1: number, col1: number, row2: number, col2: number): void {
        this.isProcessing = true;
        this.moves++;

        // Swap data
        this._swapData(row1, col1, row2, col2);
        // Animate swap
        this._animateSwap(row1, col1, row2, col2, () => {
            // Check for matches
            const matches = this._findMatches();
            if (matches.length > 0) {
                this._processMatches(matches);
            } else {
                // No match - swap back
                this._swapData(row1, col1, row2, col2);
                this._animateSwap(row1, col1, row2, col2, () => {
                    this.isProcessing = false;
                });
            }
        });
    }

    /** Swap cell data in the grid array */
    private _swapData(row1: number, col1: number, row2: number, col2: number): void {
        const temp = this.grid[row1][col1];
        this.grid[row1][col1] = this.grid[row2][col2];
        this.grid[row2][col2] = temp;

        // Update cell metadata
        if (this.grid[row1][col1]) {
            this.grid[row1][col1].row = row1;
            this.grid[row1][col1].col = col1;
        }
        if (this.grid[row2][col2]) {
            this.grid[row2][col2].row = row2;
            this.grid[row2][col2].col = col2;
        }
    }

    /** Animate the visual swap of two gems */
    private _animateSwap(
        row1: number, col1: number,
        row2: number, col2: number,
        onComplete: () => void,
    ): void {
        const cell1 = this.grid[row1][col1];
        const cell2 = this.grid[row2][col2];

        if (!cell1?.sprite || !cell2?.sprite) {
            onComplete();
            return;
        }

        const x1 = this.gridOffsetX + col1 * this.cellSize + this.cellSize / 2;
        const y1 = this.gridOffsetY + row1 * this.cellSize + this.cellSize / 2;
        const x2 = this.gridOffsetX + col2 * this.cellSize + this.cellSize / 2;
        const y2 = this.gridOffsetY + row2 * this.cellSize + this.cellSize / 2;

        let done = 0;
        const checkDone = () => { if (++done >= 2) onComplete(); };

        this.tweens.add({ targets: cell1.sprite, x: x1, y: y1, duration: 200, ease: 'Power2', onComplete: checkDone });
        this.tweens.add({ targets: cell2.sprite, x: x2, y: y2, duration: 200, ease: 'Power2', onComplete: checkDone });
    }

    /** Find all groups of 3+ matching gems */
    private _findMatches(): { row: number; col: number }[][] {
        const matched = new Set<string>();
        const groups: { row: number; col: number }[][] = [];

        // Horizontal matches
        for (let row = 0; row < GRID_SIZE; row++) {
            for (let col = 0; col < GRID_SIZE - 2; col++) {
                const ci = this.grid[row][col]?.colorIndex;
                if (ci === undefined) continue;
                let len = 1;
                while (col + len < GRID_SIZE && this.grid[row][col + len]?.colorIndex === ci) len++;
                if (len >= 3) {
                    const group: { row: number; col: number }[] = [];
                    for (let k = 0; k < len; k++) {
                        const key = `${row},${col + k}`;
                        if (!matched.has(key)) { matched.add(key); group.push({ row, col: col + k }); }
                    }
                    if (group.length > 0) groups.push(group);
                    col += len - 1;
                }
            }
        }

        // Vertical matches
        for (let col = 0; col < GRID_SIZE; col++) {
            for (let row = 0; row < GRID_SIZE - 2; row++) {
                const ci = this.grid[row][col]?.colorIndex;
                if (ci === undefined) continue;
                let len = 1;
                while (row + len < GRID_SIZE && this.grid[row + len]?.[col]?.colorIndex === ci) len++;
                if (len >= 3) {
                    const group: { row: number; col: number }[] = [];
                    for (let k = 0; k < len; k++) {
                        const key = `${row + k},${col}`;
                        if (!matched.has(key)) { matched.add(key); group.push({ row: row + k, col }); }
                    }
                    if (group.length > 0) groups.push(group);
                    row += len - 1;
                }
            }
        }

        return groups;
    }

    /** Process matched gems: animate removal, apply gravity, fill new gems */
    private _processMatches(groups: { row: number; col: number }[][]): void {
        // Calculate score
        let gemsCleared = 0;
        const allMatched: { row: number; col: number }[] = [];
        for (const group of groups) {
            for (const { row, col } of group) {
                allMatched.push({ row, col });
                gemsCleared++;
            }
        }

        // Combo bonus: +50 for 4+ match, +10 per gem otherwise
        let points = 0;
        for (const group of groups) {
            if (group.length >= 4) {
                points += 50 + (group.length - 4) * 10;
            } else {
                points += group.length * 10;
            }
        }
        this.score += points;
        this.scoreText.setText(`Score: ${this.score}`);

        // Show points popup
        this._showPointsPopup(points);

        // Animate removal
        const tweens: Phaser.Types.Tweens.TweenBuilder[] = [];
        for (const { row, col } of allMatched) {
            const cell = this.grid[row][col];
            if (cell?.sprite) {
                tweens.push({
                    targets: cell.sprite,
                    scaleX: 0,
                    scaleY: 0,
                    alpha: 0,
                    duration: 200,
                    ease: 'Power2',
                    onComplete: () => cell.sprite?.destroy(),
                });
            }
        }

        // After removal animation, apply gravity
        this.tweens.chain({
            tweens: tweens.map(t => ({ ...t })),
            onComplete: () => {
                // Clear matched cells
                for (const { row, col } of allMatched) {
                    this.grid[row][col] = { row, col, colorIndex: -1, sprite: null };
                }
                this._applyGravity();
            },
        });

        // Fallback if no tweens
        if (tweens.length === 0) {
            this._applyGravity();
        }
    }

    /** Apply gravity: gems fall down to fill empty cells, new gems spawn at top */
    private _applyGravity(): void {
        const fallAnimations: Promise<void>[] = [];

        for (let col = 0; col < GRID_SIZE; col++) {
            // Collect non-empty cells from bottom to top
            const gems: GemCell[] = [];
            for (let row = GRID_SIZE - 1; row >= 0; row--) {
                if (this.grid[row][col].colorIndex !== -1) {
                    gems.push(this.grid[row][col]);
                }
            }

            // How many new gems needed
            const emptyCount = GRID_SIZE - gems.length;

            // Place existing gems at the bottom
            for (let i = 0; i < gems.length; i++) {
                const newRow = GRID_SIZE - 1 - i;
                const cell = gems[i];
                const oldRow = cell.row;
                cell.row = newRow;
                cell.col = col;
                this.grid[newRow][col] = cell;

                // Animate falling
                if (oldRow !== newRow && cell.sprite) {
                    const newY = this.gridOffsetY + newRow * this.cellSize + this.cellSize / 2;
                    const p = new Promise<void>(resolve => {
                        this.tweens.add({
                            targets: cell.sprite,
                            y: newY,
                            duration: 150 + (oldRow - newRow) * 30,
                            ease: 'Bounce.easeOut',
                            onComplete: resolve,
                        });
                    });
                    fallAnimations.push(p);
                }
            }

            // Spawn new gems for empty slots
            for (let i = 0; i < emptyCount; i++) {
                const newRow = emptyCount - 1 - i;
                const colorIndex = Phaser.Math.Between(0, GEM_COLORS.length - 1);

                // Create gem above visible area
                const x = this.gridOffsetX + col * this.cellSize + this.cellSize / 2;
                const startY = this.gridOffsetY + (i - emptyCount) * this.cellSize - this.cellSize / 2;

                const sprite = this.add.circle(x, startY, this.cellSize / 2 - 4, GEM_COLORS[colorIndex]);
                sprite.setStrokeStyle(2, 0xffffff, 0.3);
                sprite.setInteractive();

                const cell: GemCell = { row: newRow, col, colorIndex, sprite };
                this.grid[newRow][col] = cell;

                const newY = this.gridOffsetY + newRow * this.cellSize + this.cellSize / 2;
                const p = new Promise<void>(resolve => {
                    this.tweens.add({
                        targets: sprite,
                        y: newY,
                        duration: 200 + i * 50,
                        ease: 'Bounce.easeOut',
                        onComplete: resolve,
                    });
                });
                fallAnimations.push(p);
            }
        }

        // After all falls complete, check for chain matches
        if (fallAnimations.length > 0) {
            Promise.all(fallAnimations).then(() => {
                const newMatches = this._findMatches();
                if (newMatches.length > 0) {
                    // Chain reaction!
                    this._processMatches(newMatches);
                } else {
                    this.isProcessing = false;
                }
            });
        } else {
            this.isProcessing = false;
        }
    }

    /** Show floating score popup */
    private _showPointsPopup(points: number): void {
        const { width } = this.scale;
        const text = this.add.text(width / 2, 80, `+${points}`, {
            fontSize: '22px',
            color: '#ffff00',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        this.tweens.add({
            targets: text,
            y: 50,
            alpha: 0,
            duration: 800,
            ease: 'Power2',
            onComplete: () => text.destroy(),
        });
    }

    /** Find cell by its sprite */
    private _getCellBySprite(sprite: Phaser.GameObjects.Arc): GemCell | null {
        for (let row = 0; row < GRID_SIZE; row++) {
            for (let col = 0; col < GRID_SIZE; col++) {
                if (this.grid[row][col]?.sprite === sprite) {
                    return this.grid[row][col];
                }
            }
        }
        return null;
    }
}
