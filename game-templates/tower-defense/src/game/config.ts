/**
 * __GAME_CONFIG__ — Single source of truth for all coordinates and tuning.
 *
 * CRITICAL: All game code MUST reference this object for positions, sizes,
 * and grid layout. No hardcoded pixel values allowed anywhere else.
 */

export const __GAME_CONFIG__ = {
  canvas: { width: 800, height: 600 },

  grid: {
    cellSize: 40,
    cols: 20,
    rows: 15,
    offsetX: 0,
    offsetY: 0,
  },

  path: {
    color: 0x8b7355,
    width: 38,
  },

  buildable: {
    color: 0x2d5a1e,
    alpha: 0.3,
  },

  economy: {
    startGold: 100,
  },

  base: {
    maxHp: 20,
  },

  waves: {
    count: 10,
  },

  hud: {
    gold: { x: 16, y: 20 },
    hp: { x: 16, y: 48 },
    wave: { x: 700, y: 20 },
    towerMenu: { y: 540 },
    fontSize: 18,
    fontFamily: 'Arial',
    color: '#ffffff',
  },

  tower: {
    rangeCircleAlpha: 0.2,
    rangeCircleWidth: 2,
    placementPreviewAlpha: 0.5,
  },
} as const;

/** Convert grid cell (col, row) to screen center pixel coordinates. */
export function gridToScreen(col: number, row: number): { x: number; y: number } {
  const { cellSize, offsetX, offsetY } = __GAME_CONFIG__.grid;
  return {
    x: offsetX + col * cellSize + cellSize / 2,
    y: offsetY + row * cellSize + cellSize / 2,
  };
}

/** Convert screen pixel coordinates to grid cell (col, row). */
export function screenToGrid(x: number, y: number): { col: number; row: number } {
  const { cellSize, offsetX, offsetY } = __GAME_CONFIG__.grid;
  return {
    col: Math.floor((x - offsetX) / cellSize),
    row: Math.floor((y - offsetY) / cellSize),
  };
}

export function isValidCell(col: number, row: number): boolean {
  const { cols, rows } = __GAME_CONFIG__.grid;
  return col >= 0 && col < cols && row >= 0 && row < rows;
}
