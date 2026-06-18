import { Waypoint } from '../entities/Enemy';

export class PathFinder {
  readonly waypoints: Waypoint[];

  constructor(waypoints: Waypoint[]) {
    this.waypoints = waypoints;
  }

  getStart(): Waypoint {
    return this.waypoints[0] ?? { x: 0, y: 0 };
  }

  getEnd(): Waypoint {
    return this.waypoints[this.waypoints.length - 1] ?? { x: 0, y: 0 };
  }

  isOnPath(col: number, row: number, cellSize: number): boolean {
    const cx = col * cellSize + cellSize / 2;
    const cy = row * cellSize + cellSize / 2;
    const halfWidth = cellSize / 2 + 4;

    for (let i = 0; i < this.waypoints.length - 1; i++) {
      const a = this.waypoints[i];
      const b = this.waypoints[i + 1];
      if (this.pointNearSegment(cx, cy, a.x, a.y, b.x, b.y, halfWidth)) {
        return true;
      }
    }
    return false;
  }

  private pointNearSegment(
    px: number, py: number,
    ax: number, ay: number,
    bx: number, by: number,
    threshold: number,
  ): boolean {
    const dx = bx - ax;
    const dy = by - ay;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) {
      const ddx = px - ax;
      const ddy = py - ay;
      return ddx * ddx + ddy * ddy <= threshold * threshold;
    }
    let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    const projX = ax + t * dx;
    const projY = ay + t * dy;
    const ddx = px - projX;
    const ddy = py - projY;
    return ddx * ddx + ddy * ddy <= threshold * threshold;
  }
}
