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

        // Make form labels tappable for info popups (process, bean color, bean size)
        document.querySelectorAll('.field-select').forEach(select => {
            var wrapper = select.closest('.field');
            if (!wrapper) return;
            var label = wrapper.querySelector('label');
            if (!label) return;
            if (select.name === 'process') {
                label.classList.add('info-link');
                label.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    var info = getInfo('processes', select.value);
                    if (info) showPopup(label, info, select.value);
                    else closePopup();
                });
            }
            if (select.name === 'bean_color') {
                label.classList.add('info-link');
                label.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    showRoastGuide();
                });
            }
            if (select.name === 'bean_size') {
                label.classList.add('info-link');
                label.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    showBeanSizeGuide();
                });
            }
        });

        // Origin map preview — updates live as user types country
        attachOriginMapPreview();
    }

    function showRoastGuide() {
        closePopup();
        var overlay = document.createElement('div');
        overlay.className = 'roast-guide-overlay';
        overlay.innerHTML =
            '<div class="roast-guide-panel">' +
                '<div class="info-popup-title">Roast Level Guide</div>' +
                '<img src="/static/roast-guide.png" class="roast-guide-img" alt="Coffee roast levels from light to dark">' +
                '<div class="roast-guide-hint">Tap anywhere to close</div>' +
            '</div>';
        overlay.addEventListener('pointerdown', function() { closePopup(); });
        document.body.appendChild(overlay);
        activePopup = overlay;
        void overlay.offsetHeight;
    }

    function showBeanSizeGuide() {
        closePopup();
        var overlay = document.createElement('div');
        overlay.className = 'roast-guide-overlay';
        overlay.innerHTML =
            '<div class="roast-guide-panel bean-size-panel">' +
                '<div class="info-popup-title">Bean Size Guide</div>' +
                '<table class="bean-size-table">' +
                    '<tr><th>Size</th><th>Screen</th><th>Diameter</th><th>Typical</th></tr>' +
                    '<tr><td><strong>Small</strong></td><td>14–15</td><td>&lt; 6 mm</td><td>Robusta, some Ethiopian</td></tr>' +
                    '<tr><td><strong>Medium</strong></td><td>16–17</td><td>6–7 mm</td><td>Most Arabica (default)</td></tr>' +
                    '<tr><td><strong>Large</strong></td><td>18–20</td><td>7–8 mm</td><td>Kenya AA, Colombia Supremo</td></tr>' +
                    '<tr><td><strong>Peaberry</strong></td><td>varies</td><td>round</td><td>Single seed, any origin</td></tr>' +
                '</table>' +
                '<div class="bean-size-hint">Screen number = diameter in 1/64 inch. Most specialty bags list the screen size or grade (AA, Supremo, etc).</div>' +
                '<div class="roast-guide-hint">Tap anywhere to close</div>' +
            '</div>';
        overlay.addEventListener('pointerdown', function() { closePopup(); });
        document.body.appendChild(overlay);
        activePopup = overlay;
        void overlay.offsetHeight;
    }

    var mapIndex = null;
    function attachOriginMapPreview() {
        var input = document.getElementById('origin_country');
        var preview = document.getElementById('originMapPreview');
        if (!input || !preview) return;

        // Load map index
        fetch('/static/maps/origin-map-index.json')
            .then(function(r) { return r.json(); })
            .then(function(data) { mapIndex = data; updateMapPreview(); })
            .catch(function() {});

        var lastVal = '';
        input.addEventListener('input', updateMapPreview);
        input.addEventListener('change', updateMapPreview);
        input.addEventListener('blur', updateMapPreview);
        // Keyboard/autocomplete may set value without events — poll lightly
        setInterval(function() {
            var cur = (input.value || '').trim().toLowerCase();
            if (cur !== lastVal) updateMapPreview();
        }, 500);

        function updateMapPreview() {
            if (!mapIndex) return;
            var val = (input.value || '').trim().toLowerCase();
            lastVal = val;
            var file = mapIndex[val];
            if (file) {
                preview.innerHTML = '<img src="/static/maps/' + file + '" alt="' + esc(input.value) + '">';
            } else {
                preview.innerHTML = '';
            }
        }
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
