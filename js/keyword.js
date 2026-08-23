document.addEventListener('DOMContentLoaded', () => {
    const cacheBuster = `v=${Math.floor(Date.now() / 600000)}`;
    let data = null;

    const els = {
        subtitle: document.getElementById('kw-subtitle'),
        summary: document.getElementById('kw-summary'),
        list: document.getElementById('kw-list'),
    };

    init();

    async function init() {
        try {
            const resp = await fetch(`data/title_keywords.json?${cacheBuster}`);
            if (!resp.ok) throw new Error('Failed to load');
            data = await resp.json();

            els.subtitle.textContent = `${data.date} · 共 ${data.total_keywords} 个关键词 · ${data.total_books} 本书`;

            render();
        } catch (err) {
            console.error(err);
            els.summary.textContent = '数据加载失败，请稍后刷新。';
        }
    }

    function render() {
        if (!data) return;

        let kws = data.male_keywords;

        if (!kws || !kws.length) {
            els.list.innerHTML = '<p class="muted-line">暂无数据。</p>';
            return;
        }

        // Summary text
        const top3 = kws.slice(0, 3).map(k => `"${k.keyword}"(${k.count}本)`).join('、');
        els.summary.textContent = `男频上榜书名中，${top3} 出现频率最高。点击查看对应书籍。`;

        els.list.innerHTML = kws.slice(0, 50).map((kw, i) => {
            return `
                <div class="hot-type-row hot-type-row-static ${kw.count >= 10 ? 'genre-row' : ''}">
                    <span>${i + 1}</span>
                    <strong>${escapeHtml(kw.keyword)}</strong>
                    <small>${kw.count}本 · 均读${formatNum(kw.avg_reads)} · 最高${formatNum(kw.max_reads)}</small>
                    <em>${kw.count}</em>
                </div>
            `;
        }).join('');

        // Add expand/collapse for sample books
        els.list.querySelectorAll('.hot-type-row').forEach((row, i) => {
            if (i >= kws.length) return;
            row.addEventListener('click', () => toggleSamples(row, kws[i]));
        });
    }

    function toggleSamples(row, kw) {
        const existing = row.nextElementSibling;
        if (existing && existing.classList.contains('kw-samples')) {
            existing.remove();
            return;
        }
        if (!kw.sample_books || !kw.sample_books.length) return;
        const div = document.createElement('div');
        div.className = 'kw-samples';
        div.innerHTML = kw.sample_books.map(b => `
            <div class="compact-row">
                <div><strong>${escapeHtml(b.title)}</strong><small>${escapeHtml(b.category)} · ${escapeHtml(b.reads)}</small></div>
            </div>
        `).join('');
        row.after(div);
    }

    function formatNum(n) {
        if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
        return String(Math.round(n));
    }

    function escapeHtml(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
});
