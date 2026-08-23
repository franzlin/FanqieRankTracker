document.addEventListener('DOMContentLoaded', () => {
    const cacheBuster = `v=${Math.floor(Date.now() / 600000)}`;
    let data = null;

    const els = {
        subtitle: document.getElementById('op-subtitle'),
        ai: document.getElementById('op-ai'),
        maleList: document.getElementById('op-male-list'),
        femaleList: document.getElementById('op-female-list'),
        maleTitle: document.getElementById('op-male-title'),
        femaleTitle: document.getElementById('op-female-title'),
    };

    init();

    async function init() {
        try {
            const resp = await fetch(`data/opening_analysis.json?${cacheBuster}`);
            if (!resp.ok) throw new Error('Failed to load');
            data = await resp.json();

            els.subtitle.textContent = `${data.date} · 新上榜 ${data.total_new} 本（男${data.male_count} / 女${data.female_count}）`;
            els.maleTitle.textContent = `男频新上榜 ${data.male_count} 本`;
            els.femaleTitle.textContent = `女频新上榜 ${data.female_count} 本`;

            renderAI();
            renderList(els.maleList, data.male_openings);
            renderList(els.femaleList, data.female_openings);
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
        // Bold sections as block headers
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Book titles
        html = html.replace(/《(.+?)》/g, '<span class="book-mark">《$1》</span>');
        // Convert newlines before ** to proper spacing
        html = html.replace(/\n(?=\*\*)/g, '\n\n');
        html = html.replace(/\n/g, '<br>');
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
                    <span class="op-book-title">${escapeHtml(item.title)}</span>
                    <span class="op-book-meta">${escapeHtml(item.category)} · ${escapeHtml(item.reads)} · ${escapeHtml(item.author)}</span>
                    <span class="op-book-intro">${escapeHtml(intro)}</span>
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
