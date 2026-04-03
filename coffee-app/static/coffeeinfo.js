(function() {
    let INFO = null;
    let activePopup = null;

    fetch('/static/coffee-info.json')
        .then(r => r.json())
        .then(data => {
            INFO = data;
            attachInfoIcons();
        })
        .catch(() => {});

    function getInfo(type, name) {
        if (!INFO || !INFO[type]) return null;
        // Try exact match, then case-insensitive
        return INFO[type][name] || INFO[type][Object.keys(INFO[type]).find(
            k => k.toLowerCase() === name.toLowerCase()
        )] || null;
    }

    function showPopup(el, info, title) {
        closePopup();
        const popup = document.createElement('div');
        popup.className = 'info-popup';
        const parts = [
            '<div class="info-popup-title">' + esc(title) + (info.species ? ' <span class="info-species">' + esc(info.species) + '</span>' : '') + '</div>',
            '<div class="info-popup-desc">' + esc(info.desc) + '</div>',
        ];
        if (info.flavor) parts.push('<div class="info-popup-flavor"><strong>Flavor:</strong> ' + esc(info.flavor) + '</div>');
        if (info.note) parts.push('<div class="info-popup-note"><strong>Tip:</strong> ' + esc(info.note) + '</div>');
        popup.innerHTML = parts.join('');
        el.parentNode.style.position = 'relative';
        el.parentNode.appendChild(popup);
        activePopup = popup;
        // Force layout for Wayland
        void popup.offsetHeight;
    }

    function closePopup() {
        if (activePopup) {
            activePopup.remove();
            activePopup = null;
        }
    }

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function attachInfoIcons() {
        // Skip coffee-meta (overview cards — tapping those navigates to sample page)
        // Only attach to coffee-detail (sample page, stats page, eval page)
        document.querySelectorAll('.coffee-detail span').forEach(span => {
            const text = span.textContent.trim();
            const info = getInfo('varieties', text) || getInfo('processes', text);
            if (info) makeClickable(span, text, info);
        });

        // Evaluation dimension labels
        document.querySelectorAll('.eval-label').forEach(span => {
            const text = span.textContent.trim();
            const info = getInfo('dimensions', text);
            if (info) makeClickable(span, text, info);
        });

        // Also check select dropdowns on form pages (process)
        document.querySelectorAll('.field-select').forEach(select => {
            if (select.name === 'process') {
                const wrapper = select.closest('.field');
                if (!wrapper) return;
                const icon = document.createElement('span');
                icon.className = 'info-icon';
                icon.textContent = 'ⓘ';
                icon.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    const info = getInfo('processes', select.value);
                    if (info) showPopup(icon, info, select.value);
                });
                wrapper.querySelector('label').appendChild(document.createTextNode(' '));
                wrapper.querySelector('label').appendChild(icon);
            }
        });
    }

    function makeClickable(span, name, info) {
        span.classList.add('info-link');
        span.addEventListener('pointerdown', e => {
            e.preventDefault();
            e.stopPropagation();
            if (activePopup && activePopup.parentNode === span.parentNode) {
                closePopup();
            } else {
                showPopup(span, info, name);
            }
        });
    }

    // Close popup on outside tap
    document.addEventListener('pointerdown', e => {
        if (activePopup && !activePopup.contains(e.target) && !e.target.classList.contains('info-icon') && !e.target.classList.contains('info-link')) {
            closePopup();
        }
    });
})();
