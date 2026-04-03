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
        popup.innerHTML = [
            '<div class="info-popup-title">' + esc(title) + '</div>',
            '<div class="info-popup-desc">' + esc(info.desc) + '</div>',
            '<div class="info-popup-flavor"><strong>Flavor:</strong> ' + esc(info.flavor) + '</div>',
            '<div class="info-popup-note"><strong>Tip:</strong> ' + esc(info.note) + '</div>',
        ].join('');
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
        // Find variety and process text in coffee-meta and coffee-detail spans
        document.querySelectorAll('.coffee-meta span, .coffee-detail span').forEach(span => {
            const text = span.textContent.trim();
            // Check varieties
            const varInfo = getInfo('varieties', text);
            if (varInfo) {
                addIcon(span, 'varieties', text, varInfo);
                return;
            }
            // Check processes
            const procInfo = getInfo('processes', text);
            if (procInfo) {
                addIcon(span, 'processes', text, procInfo);
            }
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

    function addIcon(span, type, name, info) {
        const icon = document.createElement('span');
        icon.className = 'info-icon';
        icon.textContent = 'ⓘ';
        icon.addEventListener('pointerdown', e => {
            e.preventDefault();
            e.stopPropagation();
            if (activePopup && activePopup.parentNode === span.parentNode) {
                closePopup();
            } else {
                showPopup(span, info, name);
            }
        });
        span.appendChild(document.createTextNode(' '));
        span.appendChild(icon);
    }

    // Close popup on outside tap
    document.addEventListener('pointerdown', e => {
        if (activePopup && !activePopup.contains(e.target) && !e.target.classList.contains('info-icon')) {
            closePopup();
        }
    });
})();
