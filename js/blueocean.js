document.addEventListener('DOMContentLoaded', () => {
    const cacheBuster = `v=${Math.floor(Date.now() / 600000)}`;
    let data = null;
    let selectedCategory = '';

    const els = {
        subtitle: document.getElementById('bo-subtitle'),
        categoryButtons: document.getElementById('bo-category-buttons'),
        currentCat: document.getElementById('bo-current-cat'),
        tagList: document.getElementById('bo-tag-list'),
    };

    init();

    async function init() {
        try {
            const resp = await fetch(`data/blueocean.json?${cacheBuster}`);
            if (!resp.ok) throw new Error('Failed to load');
            data = await resp.json();

            els.subtitle.textContent = `${data.date} · ${data.categories.length} 个分类`;

            renderCategoryButtons();
            renderTags();
        } catch (err) {
            console.error(err);
            els.tagList.innerHTML = '<p class="muted-line">数据加载失败。</p>';
        }
    }

    function getFiltered() {
        return data.categories.filter(c => c.channel === 'male');
    }

    function renderCategoryButtons() {
        const filtered = getFiltered();
        els.categoryButtons.innerHTML = filtered.map(cat => `
            <button class="category-chip${cat.name === selectedCategory ? ' active' : ''}" type="button" data-cat="${escapeAttr(cat.name)}">
                ${escapeHtml(cat.name)}
                ${cat.blue_count > 0 ? `<span class="cat-badge new">蓝${cat.blue_count}</span>` : ''}
            </button>
        `).join('');

        els.categoryButtons.querySelectorAll('.category-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                selectedCategory = btn.dataset.cat;
                renderCategoryButtons();
                renderTags();
            });
        });

        if (!selectedCategory && filtered.length > 0) {
            // Auto-select the category with most blue tags
            const best = filtered.reduce((a, b) => b.blue_count > a.blue_count ? b : a, filtered[0]);
            if (best) {
                selectedCategory = best.name;
                renderCategoryButtons();
            }
        }
    }

    function renderTags() {
        const filtered = getFiltered();
        const cat = filtered.find(c => c.name === selectedCategory) || filtered[0];
        if (!cat) {
            els.tagList.innerHTML = '<p class="muted-line">暂无数据。</p>';
            return;
        }

        els.currentCat.textContent = `${cat.name} · ${cat.total_books}本`;

        if (!cat.tags || !cat.tags.length) {
            els.tagList.innerHTML = '<p class="muted-line">该分类暂无题材数据。</p>';
            return;
        }

        els.tagList.innerHTML = cat.tags.map(tag => {
            const levelClass = tag.level === 'blue' ? 'bo-blue' : (tag.level === 'red' ? 'bo-red' : 'bo-normal');
            const levelLabel = tag.level === 'blue' ? '蓝海' : (tag.level === 'red' ? '红海' : '正常');
            const samples = tag.sample_titles.length ? `（${tag.sample_titles.map(escapeHtml).join('、')}）` : '';
            return `
                <div class="hot-type-row ${levelClass}">
                    <span class="bo-level">${levelLabel}</span>
                    <strong>${escapeHtml(tag.tag)}</strong>
                    <small>${tag.count}/${cat.total_books}本 · 密度${Math.round(tag.density * 100)}% · 均读${formatNum(tag.avg_reads)} ${samples}</small>
                    <em>${Math.round(tag.density * 100)}%</em>
                </div>
            `;
        }).join('');
    }

    function formatNum(n) {
        if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
        return String(Math.round(n));
    }

    function escapeHtml(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function escapeAttr(s) {
        return escapeHtml(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
});
