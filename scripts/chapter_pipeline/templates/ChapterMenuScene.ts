/**
 * ChapterMenuScene — shows the chapter selection screen.
 * Loads chapter metadata from world_bible.json + cross_chapter.json.
 */
import * as Phaser from 'phaser';

interface ChapterMeta {
    id: number;
    title: string;
    synopsis: string;
    entry_node: string;
    node_count: number;
    unlocked: boolean;
}

export class ChapterMenuScene extends Phaser.Scene {
    private chapters: ChapterMeta[] = [];
    private bibleTitle: string = '';

    constructor() {
        super({ key: 'ChapterMenuScene' });
    }

    create(): void {
        this.cameras.main.setBackgroundColor('#0a0a15');
        this.loadChapterData();

        const cx = this.cameras.main.width / 2;
        this.add.text(cx, 50, this.bibleTitle, {
            fontFamily: 'Georgia, serif',
            fontSize: '42px',
            color: '#d4af37',
            fontStyle: 'bold',
        }).setOrigin(0.5);

        this.add.text(cx, 100, '抵制资本主义 · 章节选择', {
            fontFamily: 'Noto Sans CJK SC, Microsoft YaHei, sans-serif',
            fontSize: '18px',
            color: '#888',
        }).setOrigin(0.5);

        const startY = 160;
        const cardH = 110;
        const cardW = 700;
        this.chapters.forEach((ch, i) => {
            const y = startY + i * (cardH + 12);
            const card = this.add.graphics();
            card.fillStyle(ch.unlocked ? 0x14141e : 0x0a0a14, 0.85);
            card.lineStyle(2, ch.unlocked ? 0x3a3a5a : 0x2a2a3a, 1);
            card.fillRoundedRect(cx - cardW / 2, y, cardW, cardH, 10);
            card.strokeRoundedRect(cx - cardW / 2, y, cardW, cardH, 10);

            this.add.text(cx - cardW / 2 + 20, y + 16, `第 ${ch.id} 章`, {
                fontFamily: 'Noto Sans CJK SC, Microsoft YaHei, sans-serif',
                fontSize: '14px',
                color: ch.unlocked ? '#d4af37' : '#555',
            });
            this.add.text(cx - cardW / 2 + 20, y + 36, ch.title, {
                fontFamily: 'Noto Sans CJK SC, Microsoft YaHei, sans-serif',
                fontSize: '20px',
                color: ch.unlocked ? '#e0e0e0' : '#666',
                fontStyle: 'bold',
            });
            this.add.text(cx - cardW / 2 + 20, y + 68, ch.synopsis.substring(0, 70) + '...', {
                fontFamily: 'Noto Sans CJK SC, Microsoft YaHei, sans-serif',
                fontSize: '12px',
                color: ch.unlocked ? '#aaa' : '#444',
                wordWrap: { width: cardW - 40 },
            });

            if (ch.unlocked) {
                const playBtn = this.add.text(cx + cardW / 2 - 30, y + cardH / 2, '▶ 开始', {
                    fontFamily: 'Noto Sans CJK SC, Microsoft YaHei, sans-serif',
                    fontSize: '18px',
                    color: '#d4af37',
                }).setOrigin(1, 0.5).setInteractive({ useHandCursor: true });

                playBtn.on('pointerover', () => playBtn.setColor('#fff'));
                playBtn.on('pointerout', () => playBtn.setColor('#d4af37'));
                playBtn.on('pointerdown', () => this.startChapter(ch));
            } else {
                this.add.text(cx + cardW / 2 - 30, y + cardH / 2, '🔒', {
                    fontSize: '24px',
                }).setOrigin(1, 0.5);
            }
        });
    }

    private loadChapterData(): void {
        try {
            const bible = this.cache.json.get('world_bible');
            this.bibleTitle = bible?.title || 'Visual Novel';

            const branching = this.cache.json.get('branching') as any;
            const crossChapter = this.cache.json.get('cross_chapter') as any;
            const savedChapters: number[] = JSON.parse(
                localStorage.getItem('completed_chapters') || '[]'
            );

            const chapterOrder: { id: number; title: string; entry_node: string; node_count: number }[] =
                branching?.chapter_order || [];

            this.chapters = chapterOrder.map((ch, i) => ({
                id: ch.id,
                title: ch.title,
                synopsis: this.synopsisForChapter(ch.id),
                entry_node: ch.entry_node,
                node_count: ch.node_count,
                unlocked: i === 0 || savedChapters.includes(ch.id - 1),
            }));
        } catch (e) {
            console.error('Failed to load chapter data:', e);
            this.chapters = [{
                id: 1, title: '第一章', synopsis: '故事开始', entry_node: 'common_start',
                node_count: 0, unlocked: true,
            }];
        }
    }

    private synopsisForChapter(id: number): string {
        const synopses: Record<number, string> = {
            1: '林月在巨型公司Omnicorp的例行审计中发现财务异常，偶遇神秘工运领袖李伟，被迫做出第一个道德抉择。',
            2: '主角深入接触劳工组织，了解数字游民陈雪的故事，面临是否泄露公司机密的抉择，黑客Zhao Ming登场。',
            3: '公司安保升级，主角在追查中遭遇背叛（Zhang Yan），工人运动受挫，团队必须重组。',
            4: '主角和盟友策划一次大胆行动，必须牺牲部分安全换取关键证据。',
            5: '最终对决Omnicorp CEO，多个结局分支根据之前积累的道德抉择展开。',
        };
        return synopses[id] || `第 ${id} 章`;
    }

    private startChapter(ch: ChapterMeta): void {
        localStorage.setItem('current_chapter', String(ch.id));
        localStorage.setItem('current_entry_node', ch.entry_node);
        this.scene.start('NovelScene', { entryNode: ch.entry_node, chapterId: ch.id });
    }
}
