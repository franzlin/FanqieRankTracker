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

        // Convert numbered lists like "1. ...\n2. ..." into real ordered lists
        html = html.replace(/((?:^|\n)\d+\.\s+.+?(?:\n|$))+?/gs, (match) => {
            // Ensure match starts with newline for easier parsing
            const items = ('\n' + match.trim())
                .split(/\n(?=\d+\.\s+)/)
                .map(line => line.trim())
                .filter(Boolean);
            if (items.length < 2) return match;
            const li = items
                .map(line => `<li>${line.replace(/^\d+\.\s*/, '')}</li>`)
                .join('');
            return `<ol class="op-ai-list">${li}</ol>`;
        });

        // Split into sections/paragraphs by blank lines.
        const blocks = html
            .split(/\n{2,}/)
            .map(p => p.trim())
            .filter(Boolean);

        html = blocks
            .map(p => {
                if (p.startsWith('<ol') || p.startsWith('<ul')) return p;
                return `<p>${p.replace(/\n/g, '<br>')}</p>`;
            })
            .join('');

        els.ai.innerHTML = html;
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
