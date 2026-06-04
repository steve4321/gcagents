// Top-down Shooter - WASD to move, auto-fire upward
// Enemies spawn from top and move down

const PLAYER_SPEED = 300;
const BULLET_SPEED = 500;
const ENEMY_BASE_SPEED = 120;
const FIRE_RATE = 250; // ms between shots
const MAX_HEALTH = 3;

export class GameScene extends Phaser.Scene {
    score = 0;
    health = MAX_HEALTH;
    enemyCount = 0;
    bulletCount = 0;

    private player!: Phaser.Physics.Arcade.Sprite;
    private bullets!: Phaser.Physics.Arcade.Group;
    private enemies!: Phaser.Physics.Arcade.Group;
    private cursors!: Phaser.Types.Input.Keyboard.CursorKeys;
    private wasd!: { W: Phaser.Input.Keyboard.Key; A: Phaser.Input.Keyboard.Key; S: Phaser.Input.Keyboard.Key; D: Phaser.Input.Keyboard.Key };
    private scoreText!: Phaser.GameObjects.Text;
    private healthText!: Phaser.GameObjects.Text;
    private lastFireTime = 0;
    private nextEnemySpawn = 1000;
    private difficulty = 1;
    private playerGfx!: Phaser.GameObjects.Container;
    private bgStars: Phaser.GameObjects.Arc[] = [];

    constructor() {
        super({ key: 'GameScene' });
    }

    create(): void {
        const { width, height } = this.scale;

        // Background
        this.add.rectangle(width / 2, height / 2, width, height, 0x050510);

        // Stars
        for (let i = 0; i < 40; i++) {
            const star = this.add.circle(
                Phaser.Math.Between(0, width),
                Phaser.Math.Between(0, height),
                Phaser.Math.Between(1, 2),
                0xffffff,
                Phaser.Math.FloatBetween(0.1, 0.4),
            );
            this.bgStars.push(star);
        }

        // Player - triangle ship using graphics
        const shipGfx = this.add.graphics();
        shipGfx.fillStyle(0x00ff88, 1);
        shipGfx.beginPath();
        shipGfx.moveTo(0, -18);
        shipGfx.lineTo(-14, 14);
        shipGfx.lineTo(14, 14);
        shipGfx.closePath();
        shipGfx.fillPath();
        shipGfx.lineStyle(2, 0x00ffaa);
        shipGfx.strokePath();

        // Engine glow
        shipGfx.fillStyle(0x0088ff, 0.6);
        shipGfx.fillCircle(0, 16, 5);

        this.playerGfx = this.add.container(width / 2, height - 80, [shipGfx]);

        // Physics body for player
        this.player = this.physics.add.sprite(width / 2, height - 80, '');
        this.player.setSize(28, 32);
        this.player.setCollideWorldBounds(true);
        this.player.setAlpha(0);
        (this.player.body as Phaser.Physics.Arcade.Body).setAllowGravity(false);

        // Bullets
        this.bullets = this.physics.add.group({
            allowGravity: false,
        });

        // Enemies
        this.enemies = this.physics.add.group({
            allowGravity: false,
        });

        // Collisions
        this.physics.add.overlap(this.bullets, this.enemies, this._onBulletHitEnemy, undefined, this);
        this.physics.add.overlap(this.player, this.enemies, this._onEnemyHitPlayer, undefined, this);

        // Input
        if (this.input.keyboard) {
            this.cursors = this.input.keyboard.createCursorKeys();
            this.wasd = {
                W: this.input.keyboard.addKey('W'),
                A: this.input.keyboard.addKey('A'),
                S: this.input.keyboard.addKey('S'),
                D: this.input.keyboard.addKey('D'),
            };
        } else {
            // Fallback - create dummy keys
            this.cursors = this.createCursorKeysDummy();
            this.wasd = this.createWasdDummy();
        }

        // HUD
        this.scoreText = this.add.text(width / 2, 20, 'Score: 0', {
            fontSize: '24px',
            color: '#ffffff',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        this._updateHealthDisplay();

        (window as any).__TEST__!.ready = true;
    }

    update(time: number, delta: number): void {
        // Move player
        this._handleMovement();

        // Sync player gfx with physics body
        this.playerGfx.setPosition(this.player.x, this.player.y);

        // Auto-fire
        if (time > this.lastFireTime + FIRE_RATE) {
            this._fireBullet();
            this.lastFireTime = time;
        }

        // Spawn enemies
        this.nextEnemySpawn -= delta;
        if (this.nextEnemySpawn <= 0) {
            this._spawnEnemy();
            this.difficulty = 1 + this.score / 100;
            this.nextEnemySpawn = Math.max(300, 1200 - this.difficulty * 80);
        }

        // Scroll stars
        for (const star of this.bgStars) {
            star.y += delta * 0.03;
            if (star.y > this.scale.height) {
                star.y = 0;
                star.x = Phaser.Math.Between(0, this.scale.width);
            }
        }

        // Clean up off-screen bullets
        const bulletChildren = this.bullets.getChildren() as Phaser.Physics.Arcade.Sprite[];
        for (const bullet of bulletChildren) {
            if (bullet.y < -20 || bullet.y > this.scale.height + 20) {
                const gfx = (bullet as any).gfx as Phaser.GameObjects.Arc;
                gfx?.destroy();
                bullet.destroy();
            }
        }

        // Clean up off-screen enemies
        const enemyChildren = this.enemies.getChildren() as Phaser.Physics.Arcade.Sprite[];
        for (const enemy of enemyChildren) {
            if (enemy.y > this.scale.height + 40) {
                const gfx = (enemy as any).gfx as Phaser.GameObjects.Rectangle;
                gfx?.destroy();
                enemy.destroy();
            }
        }

        // Update bullet count for __TEST__
        this.bulletCount = this.bullets.getChildren().length;
    }

    private _handleMovement(): void {
        const body = this.player.body as Phaser.Physics.Arcade.Body;
        let vx = 0;
        let vy = 0;

        if (this.cursors.left.isDown || this.wasd.A.isDown) vx -= PLAYER_SPEED;
        if (this.cursors.right.isDown || this.wasd.D.isDown) vx += PLAYER_SPEED;
        if (this.cursors.up.isDown || this.wasd.W.isDown) vy -= PLAYER_SPEED;
        if (this.cursors.down.isDown || this.wasd.S.isDown) vy += PLAYER_SPEED;

        // Normalize diagonal movement
        if (vx !== 0 && vy !== 0) {
            const factor = Math.SQRT1_2;
            vx *= factor;
            vy *= factor;
        }

        body.setVelocity(vx, vy);
    }

    private _fireBullet(): void {
        const bullet = this.physics.add.sprite(this.player.x, this.player.y - 20, '');
        bullet.setSize(4, 12);
        bullet.setAlpha(0);
        (bullet.body as Phaser.Physics.Arcade.Body).setAllowGravity(false);
        bullet.setVelocityY(-BULLET_SPEED);

        // Bullet visual
        const gfx = this.add.circle(this.player.x, this.player.y - 20, 3, 0xffff44);
        gfx.setStrokeStyle(1, 0xffffaa);
        (bullet as any).gfx = gfx;

        // Track gfx position with bullet
        this.events.on('update', () => {
            if (bullet.active && gfx.active) {
                gfx.setPosition(bullet.x, bullet.y);
            }
        });

        this.bullets.add(bullet);
    }

    private _spawnEnemy(): void {
        const { width } = this.scale;
        const x = Phaser.Math.Between(30, width - 30);
        const speed = ENEMY_BASE_SPEED + this.difficulty * 20;
        const size = 28;

        const enemy = this.physics.add.sprite(x, -size, '');
        enemy.setSize(size, size);
        enemy.setAlpha(0);
        (enemy.body as Phaser.Physics.Arcade.Body).setAllowGravity(false);
        enemy.setVelocityY(speed);
        // Slight horizontal drift
        enemy.setVelocityX(Phaser.Math.Between(-30, 30));

        // Enemy visual - red square
        const gfx = this.add.rectangle(0, 0, size, size, 0xff4444);
        gfx.setStrokeStyle(2, 0xff8888);
        (enemy as any).gfx = gfx;

        this.events.on('update', () => {
            if (enemy.active && gfx.active) {
                gfx.setPosition(enemy.x, enemy.y);
            }
        });

        this.enemies.add(enemy);
        this.enemyCount = this.enemies.getChildren().length;
    }

    private _onBulletHitEnemy(
        bullet: Phaser.Types.Physics.Arcade.GameObjectWithBody,
        enemy: Phaser.Types.Physics.Arcade.GameObjectWithBody,
    ): void {
        // Destroy bullet
        const bulletGfx = (bullet as any).gfx as Phaser.GameObjects.Arc;
        bulletGfx?.destroy();
        bullet.destroy();

        // Destroy enemy
        const enemyGfx = (enemy as any).gfx as Phaser.GameObjects.Rectangle;
        enemyGfx?.destroy();
        enemy.destroy();

        // Score
        this.score += 10;
        this.scoreText.setText(`Score: ${this.score}`);

        // Small explosion effect
        const ex = (bullet as Phaser.Physics.Arcade.Sprite).x;
        const ey = (enemy as Phaser.Physics.Arcade.Sprite).y;
        this._spawnExplosion(ex, ey);

        this.enemyCount = this.enemies.getChildren().length;
    }

    private _onEnemyHitPlayer(
        _player: Phaser.Types.Physics.Arcade.GameObjectWithBody,
        enemy: Phaser.Types.Physics.Arcade.GameObjectWithBody,
    ): void {
        // Destroy enemy
        const enemyGfx = (enemy as any).gfx as Phaser.GameObjects.Rectangle;
        enemyGfx?.destroy();
        enemy.destroy();

        // Damage player
        this.health--;
        this._updateHealthDisplay();

        // Flash screen
        this.cameras.main.flash(150, 255, 0, 0);

        if (this.health <= 0) {
            this.registry.set('finalScore', this.score);
            this.scene.start('GameOverScene');
        }

        this.enemyCount = this.enemies.getChildren().length;
    }

    private _spawnExplosion(x: number, y: number): void {
        for (let i = 0; i < 6; i++) {
            const particle = this.add.circle(x, y, 3, 0xffaa44, 0.8);
            this.tweens.add({
                targets: particle,
                x: x + Phaser.Math.Between(-30, 30),
                y: y + Phaser.Math.Between(-30, 30),
                alpha: 0,
                scale: 0.2,
                duration: 300,
                onComplete: () => particle.destroy(),
            });
        }
    }

    private _updateHealthDisplay(): void {
        this.healthText?.destroy();
        const hearts = '♥'.repeat(this.health) + '♡'.repeat(MAX_HEALTH - this.health);
        this.healthText = this.add.text(this.scale.width - 20, 20, hearts, {
            fontSize: '24px',
            color: '#ff4444',
            fontFamily: 'monospace',
        }).setOrigin(1, 0);
    }

    /** Create dummy cursor keys for type safety */
    private createCursorKeysDummy(): Phaser.Types.Input.Keyboard.CursorKeys {
        const dummyKey = { isDown: false, isUp: true } as Phaser.Input.Keyboard.Key;
        return {
            up: dummyKey, down: dummyKey, left: dummyKey, right: dummyKey,
            shift: dummyKey, space: dummyKey,
        };
    }

    /** Create dummy WASD keys */
    private createWasdDummy(): { W: Phaser.Input.Keyboard.Key; A: Phaser.Input.Keyboard.Key; S: Phaser.Input.Keyboard.Key; D: Phaser.Input.Keyboard.Key } {
        const dummyKey = { isDown: false, isUp: true } as Phaser.Input.Keyboard.Key;
        return { W: dummyKey, A: dummyKey, S: dummyKey, D: dummyKey };
    }
}
