import * as Phaser from 'phaser';

export interface Waypoint {
  x: number;
  y: number;
}

export interface EnemyData {
  key: string;
  hp: number;
  speed: number;
  goldReward: number;
  baseDamage: number;
  radius: number;
  color: number;
}

export class Enemy extends Phaser.GameObjects.Container {
  hp = 0;
  maxHp = 0;
  speed = 0;
  goldReward = 0;
  baseDamage = 0;
  radius = 10;

  private enemyBody!: Phaser.GameObjects.Arc;
  private hpBar!: Phaser.GameObjects.Rectangle;
  private hpBarBg!: Phaser.GameObjects.Rectangle;

  private waypointIndex = 0;
  private slowTimer = 0;
  private slowFactor = 1;
  isDead = false;
  reachedEnd = false;

  get waypointProgress(): number {
    return this.waypointIndex;
  }

  private readonly HP_BAR_WIDTH = 30;
  private readonly HP_BAR_HEIGHT = 4;
  private readonly HP_BAR_OFFSET = 18;

  init(data: EnemyData, waypoints: Waypoint[]): void {
    this.hp = data.hp;
    this.maxHp = data.hp;
    this.speed = data.speed;
    this.goldReward = data.goldReward;
    this.baseDamage = data.baseDamage;
    this.radius = data.radius;
    this.waypointIndex = 0;
    this.slowTimer = 0;
    this.slowFactor = 1;
    this.isDead = false;
    this.reachedEnd = false;

    if (waypoints.length > 0) {
      this.setPosition(waypoints[0].x, waypoints[0].y);
    }

    this.enemyBody = this.scene.add.circle(0, 0, this.radius, data.color);
    this.enemyBody.setStrokeStyle(2, 0x000000, 0.4);
    this.add(this.enemyBody);

    this.hpBarBg = this.scene.add.rectangle(0, -this.HP_BAR_OFFSET, this.HP_BAR_WIDTH, this.HP_BAR_HEIGHT, 0x000000, 0.5);
    this.add(this.hpBarBg);

    this.hpBar = this.scene.add.rectangle(0, -this.HP_BAR_OFFSET, this.HP_BAR_WIDTH, this.HP_BAR_HEIGHT, 0xe74c3c);
    this.hpBar.setOrigin(0.5, 0.5);
    this.add(this.hpBar);

    this.setVisible(true);
    this.setActive(true);
  }

  reset(): void {
    this.removeAll(true);
    this.hp = 0;
    this.isDead = true;
    this.reachedEnd = false;
    this.waypointIndex = 0;
    this.slowTimer = 0;
    this.slowFactor = 1;
    this.setVisible(false);
    this.setActive(false);
  }

  update(delta: number, waypoints: Waypoint[]): void {
    if (this.isDead || this.reachedEnd) return;

    const dt = delta / 1000;

    if (this.slowTimer > 0) {
      this.slowTimer -= delta;
      if (this.slowTimer <= 0) {
        this.slowFactor = 1;
      }
    }

    if (this.waypointIndex >= waypoints.length - 1) {
      this.reachedEnd = true;
      return;
    }

    const target = waypoints[this.waypointIndex + 1];
    const dx = target.x - this.x;
    const dy = target.y - this.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    const moveDist = this.speed * this.slowFactor * dt;

    if (dist <= moveDist) {
      this.setPosition(target.x, target.y);
      this.waypointIndex++;
    } else {
      this.x += (dx / dist) * moveDist;
      this.y += (dy / dist) * moveDist;
    }
  }

  takeDamage(amount: number): void {
    this.hp = Math.max(0, this.hp - amount);
    const ratio = this.maxHp > 0 ? this.hp / this.maxHp : 0;
    this.hpBar.width = this.HP_BAR_WIDTH * ratio;
    if (this.hp <= 0) {
      this.isDead = true;
    }
  }

  applySlow(factor: number, duration: number): void {
    if (factor < this.slowFactor) {
      this.slowFactor = factor;
    }
    this.slowTimer = Math.max(this.slowTimer, duration);
  }

  getDistanceTo(x: number, y: number): number {
    const dx = x - this.x;
    const dy = y - this.y;
    return Math.sqrt(dx * dx + dy * dy);
  }
}
