document.addEventListener('DOMContentLoaded', () => {
    const cacheBuster = `v=${Math.floor(Date.now() / 600000)}`;
    let data = null;

    const els = {
        subtitle: document.getElementById('op-subtitle'),
        ai: document.getElementById('op-ai'),
        maleList: document.getElementById('op-male-list'),
        maleTitle: document.getElementById('op-male-title'),
    };

    init();

    async function init() {
        try {
            const resp = await fetch(`data/opening_analysis.json?${cacheBuster}`);
            if (!resp.ok) throw new Error('Failed to load');
            data = await resp.json();

            els.subtitle.textContent = `${data.date} · 男频新上榜 ${data.male_count} 本`;
            els.maleTitle.textContent = `男频新上榜 ${data.male_count} 本`;

            renderAI();
            renderList(els.maleList, data.male_openings);
        } catch (err) {
            console.error(err);
            els.ai.innerHTML = '<p class="muted-line">数据加载失败。</p>';
        }
    }

    function renderAI() {
        const text = data.ai_analysis || '';
        if (!text) {
            els.ai.innerHTML = '<p class="muted-line">AI 分析暂不可用。</p>';
            return;
        }
        let html = escapeHtml(text);
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/《(.+?)》/g, '<span class="book-mark">《$1》</span>');

        // Process line-by-line: headings, numbered lists, paragraphs
        const lines = html.split('\n');
        const blocks = [];
        let currentParagraph = [];
        let listItems = [];

        function flushParagraph() {
            if (currentParagraph.length) {
                blocks.push(`<p>${currentParagraph.join('<br>')}</p>`);
                currentParagraph = [];
            }
        }
        function flushList() {
            if (listItems.length) {
                const li = listItems.map(item => `<li>${item}</li>`).join('');
                blocks.push(`<ol class="op-ai-list">${li}</ol>`);
                listItems = [];
            }
        }

        lines.forEach(line => {
            line = line.trim();
            if (!line) return; // skip blank lines, they act as separators

            const listMatch = line.match(/^(\d+)\.\s*(.+)$/);
            if (listMatch) {
                // Start of a list item
                if (currentParagraph.length) {
                    // If previous paragraph only contained a heading, keep it; otherwise flush it.
                    const prev = currentParagraph.join('<br>');
                    if (prev.includes('<strong>')) {
                        // likely a heading, finish the paragraph first
                        flushParagraph();
                    } else {
                        flushParagraph();
                    }
                }
                listItems.push(listMatch[2]);
            } else if (line.startsWith('<strong>') && line.includes('</strong>')) {
                // Heading line (starts with bold)
                flushList();
                flushParagraph();
                currentParagraph.push(line);
            } else {
                // Regular text
                flushList();
                currentParagraph.push(line);
            }
        });
        flushList();
        flushParagraph();

        els.ai.innerHTML = blocks.join('');
    }

    function renderList(container, openings) {
        if (!openings || !openings.length) {
            container.innerHTML = '<p class="muted-line">暂无新上榜作品。</p>';
            return;
        }
        container.innerHTML = openings.map(item => {
            const intro = (item.intro || '').slice(0, 100);
            const url = item.url || '#';
            return `
                <a class="op-book-item" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">
                    <div class="op-book-title">${escapeHtml(item.title)}</div>
                    <div class="op-book-meta">${escapeHtml(item.category)} · ${escapeHtml(item.reads)} · ${escapeHtml(item.author)}</div>
                    <div class="op-book-intro">${escapeHtml(intro)}</div>
                </a>
            `;
        }).join('');
    }

    function escapeHtml(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function escapeAttr(s) {
        return escapeHtml(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
});
