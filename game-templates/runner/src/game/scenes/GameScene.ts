// Endless Runner - auto-run right, jump over obstacles
// Space/click to jump, gravity pulls back down

const GROUND_Y = 500;
const PLAYER_SIZE = 40;
const OBSTACLE_WIDTH = 30;
const OBSTACLE_HEIGHT = 50;
const SCROLL_SPEED = 300;
const JUMP_VELOCITY = -500;

export class GameScene extends Phaser.Scene {
    score = 0;
    isAlive = false;
    jumpCount = 0;
    obstacleCount = 0;

    private player!: Phaser.Physics.Arcade.Sprite;
    private ground!: Phaser.Physics.Arcade.StaticGroup;
    private obstacles!: Phaser.Physics.Arcade.Group;
    private scoreText!: Phaser.GameObjects.Text;
    private bgStars: Phaser.GameObjects.Arc[] = [];
    private bgBuildings: Phaser.GameObjects.Rectangle[] = [];
    private nextObstacleTime = 0;
    private obstacleInterval = 1500; // ms between obstacles
    private speedMultiplier = 1;

    constructor() {
        super({ key: 'GameScene' });
    }

    create(): void {
        const { width, height } = this.scale;

        // Background gradient (dark sky)
        this.add.rectangle(width / 2, height / 2, width, height, 0x0a0a1a);

        // Stars in background
        for (let i = 0; i < 30; i++) {
            const star = this.add.circle(
                Phaser.Math.Between(0, width),
                Phaser.Math.Between(20, GROUND_Y - 100),
                Phaser.Math.Between(1, 2),
                0xffffff,
                Phaser.Math.FloatBetween(0.2, 0.6),
            );
            this.bgStars.push(star);
        }

        // Background buildings (parallax)
        for (let i = 0; i < 8; i++) {
            const bw = Phaser.Math.Between(40, 80);
            const bh = Phaser.Math.Between(80, 200);
            const bx = i * 120;
            const building = this.add.rectangle(bx, GROUND_Y - bh / 2, bw, bh, 0x222244, 0.6);
            this.bgBuildings.push(building);
        }

        // Ground
        const groundRect = this.add.rectangle(width / 2, GROUND_Y + 20, width * 2, 40, 0x333355);
        this.ground = this.physics.add.staticGroup();
        this.ground.add(groundRect);
        (groundRect.body as Phaser.Physics.Arcade.StaticBody).setSize(width * 2, 40).setOffset(0, 0);

        // Ground line
        this.add.rectangle(width / 2, GROUND_Y, width * 2, 4, 0x4466aa);

        // Player
        this.player = this.physics.add.sprite(150, GROUND_Y - PLAYER_SIZE / 2, '');
        this.player.setSize(PLAYER_SIZE, PLAYER_SIZE);
        this.player.setDisplaySize(PLAYER_SIZE, PLAYER_SIZE);
        this.player.setCollideWorldBounds(true);
        this.player.setBounce(0);

        // Draw player as a colored rectangle using a render texture workaround
        // Since no sprites, we'll create a graphics object and track it
        const playerGfx = this.add.rectangle(0, 0, PLAYER_SIZE, PLAYER_SIZE, 0x00ff88);
        this.player.setAlpha(0); // Hide the default sprite
        // We'll position the gfx manually in update

        // Store reference for positioning
        (this.player as any).gfx = playerGfx;

        // Obstacles group
        this.obstacles = this.physics.add.group({
            allowGravity: false,
            immovable: true,
        });

        // Collisions
        this.physics.add.collider(this.player, this.ground);
        this.physics.add.overlap(this.player, this.obstacles, this._onHit, undefined, this);

        // Score display
        this.scoreText = this.add.text(width / 2, 30, 'Distance: 0', {
            fontSize: '24px',
            color: '#ffffff',
            fontFamily: 'monospace',
        }).setOrigin(0.5);

        // Input
        this.input.keyboard.on('keydown-SPACE', () => this._jump());
        this.input.on('pointerdown', () => this._jump());

        // Start alive
        this.isAlive = true;
        this.score = 0;
        this.jumpCount = 0;
        this.obstacleCount = 0;
        this.nextObstacleTime = 1500;
        this.speedMultiplier = 1;

        (window as any).__TEST__!.ready = true;
    }

    update(time: number, delta: number): void {
        if (!this.isAlive) return;

        // Update score (distance)
        this.score += delta * 0.1 * this.speedMultiplier;
        this.scoreText.setText(`Distance: ${Math.floor(this.score)}`);

        // Gradually increase speed
        this.speedMultiplier = 1 + Math.floor(this.score / 500) * 0.1;

        // Position player gfx over physics body
        const playerGfx = (this.player as any).gfx as Phaser.GameObjects.Rectangle;
        playerGfx.setPosition(this.player.x, this.player.y);

        // Move obstacles left
        const children = this.obstacles.getChildren() as Phaser.Physics.Arcade.Sprite[];
        for (const obs of children) {
            obs.setVelocityX(-SCROLL_SPEED * this.speedMultiplier);
            const gfx = (obs as any).gfx as Phaser.GameObjects.Rectangle;
            if (gfx && gfx.active) {
                gfx.setPosition(obs.x, obs.y);
            }
            // Remove off-screen
            if (obs.x < -OBSTACLE_WIDTH) {
                gfx?.destroy();
                obs.destroy();
            }
        }

        // Parallax background
        for (const star of this.bgStars) {
            star.x -= delta * 0.02 * this.speedMultiplier;
            if (star.x < -5) star.x = this.scale.width + 5;
        }
        for (const building of this.bgBuildings) {
            building.x -= delta * 0.05 * this.speedMultiplier;
            if (building.x < -100) building.x = this.scale.width + 100;
        }

        // Spawn obstacles
        this.nextObstacleTime -= delta;
        if (this.nextObstacleTime <= 0) {
            this._spawnObstacle();
            // Random interval with some variance, gets shorter as speed increases
            this.nextObstacleTime = (Phaser.Math.Between(1000, 2000)) / this.speedMultiplier;
        }
    }

    private _jump(): void {
        if (!this.isAlive) return;
        // Only jump if on the ground
        if (this.player.body && (this.player.body as Phaser.Physics.Arcade.Body).touching.down) {
            this.player.setVelocityY(JUMP_VELOCITY);
            this.jumpCount++;
        }
    }

    private _spawnObstacle(): void {
        const { width } = this.scale;
        const obs = this.physics.add.sprite(width + OBSTACLE_WIDTH, GROUND_Y - OBSTACLE_HEIGHT / 2, '');
        obs.setSize(OBSTACLE_WIDTH, OBSTACLE_HEIGHT);
        obs.setDisplaySize(OBSTACLE_WIDTH, OBSTACLE_HEIGHT);
        obs.setImmovable(true);
        (obs.body as Phaser.Physics.Arcade.Body).setAllowGravity(false);

        // Visual rectangle
        const gfx = this.add.rectangle(0, 0, OBSTACLE_WIDTH, OBSTACLE_HEIGHT, 0xff4444);
        gfx.setStrokeStyle(2, 0xff8888);
        (obs as any).gfx = gfx;
        obs.setAlpha(0);

        this.obstacles.add(obs);
        this.obstacleCount++;
    }

    private _onHit(): void {
        if (!this.isAlive) return;
        this.isAlive = false;

        // Flash red
        this.cameras.main.flash(200, 255, 0, 0);

        // Transition to game over after short delay
        this.time.delayedCall(500, () => {
            this.registry.set('finalScore', Math.floor(this.score));
            this.scene.start('GameOverScene');
        });
    }
}
