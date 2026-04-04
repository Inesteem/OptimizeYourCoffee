(function() {
    let INFO = null;
    let activePopup = null;
    let popupOpenedAt = 0;

    // Altitude label → meter range, per latitude band (from reference/altitude.md)
    var ALT_BANDS = {
        equatorial: {Low:"1000–1200m","Low , Medium":"1000–1600m",Medium:"1200–1600m","Medium , High":">1200m",High:">1600m","High , Medium":">1200m","Low , Medium , High":">1000m"},
        tropical: {Low:"700–900m","Low , Medium":"700–1300m",Medium:"900–1300m","Medium , High":">900m",High:">1300m","High , Medium":">900m","Low , Medium , High":">700m"},
        subtropical: {Low:"400–700m","Low , Medium":"400–1000m",Medium:"700–1000m","Medium , High":">700m",High:">1000m","High , Medium":">700m","Low , Medium , High":">400m"}
    };
    var COUNTRY_BANDS = {
        ecuador:"equatorial",colombia:"equatorial",kenya:"equatorial",uganda:"equatorial",
        rwanda:"equatorial",burundi:"equatorial",indonesia:"equatorial","dem. rep. congo":"equatorial",
        "papua new guinea":"equatorial","timor-leste":"equatorial",
        ethiopia:"tropical","costa rica":"tropical",panama:"tropical",nicaragua:"tropical",
        honduras:"tropical","el salvador":"tropical",guatemala:"tropical",jamaica:"tropical",
        vietnam:"tropical",india:"tropical",yemen:"tropical",laos:"tropical",thailand:"tropical",
        philippines:"tropical",myanmar:"tropical",cameroon:"tropical",nigeria:"tropical",
        "ivory coast":"tropical",tanzania:"tropical",malawi:"tropical",zambia:"tropical",
        madagascar:"tropical",
        brazil:"subtropical",mexico:"subtropical",peru:"subtropical",bolivia:"subtropical",
        cuba:"subtropical","dominican rep.":"subtropical",haiti:"subtropical",
        "puerto rico":"subtropical",china:"subtropical",nepal:"subtropical",
        zimbabwe:"subtropical",venezuela:"subtropical"
    };

    function resolveAltitude(label) {
        if (!label || label === 'Not applicable') return label;
        // Try to find origin country on the page
        var country = null;
        var detail = document.querySelector('.coffee-detail');
        if (detail) {
            var spans = detail.querySelectorAll('span');
            if (spans.length > 0) {
                // First span is usually "Country, City" — grab the country part
                var text = spans[0].textContent.split(',')[0].trim().toLowerCase();
                country = text;
            }
        }
        var band = COUNTRY_BANDS[country] || 'tropical';
        var resolved = (ALT_BANDS[band] || ALT_BANDS.tropical)[label];
        return resolved ? label + ' (' + resolved + ')' : label;
    }

    // Load both catalog (scraped) and manual variety data, merge manual on top
    Promise.all([
        fetch('/static/coffee-info.json').then(r => r.json()),
        fetch('/static/coffee-info-manual.json').then(r => r.json()).catch(() => ({}))
    ]).then(function(results) {
        INFO = results[0];
        var manual = results[1];
        // Merge manual varieties on top of catalog (manual wins on conflict)
        if (manual.varieties) {
            for (var k in manual.varieties) {
                INFO.varieties[k] = manual.varieties[k];
            }
        }
        attachInfoIcons();
    }).catch(() => {});

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
        const closeBtn = document.createElement('span');
        closeBtn.className = 'info-popup-close';
        closeBtn.textContent = '\u00d7';
        closeBtn.addEventListener('pointerdown', function(e) {
            e.preventDefault();
            e.stopPropagation();
            closePopup();
        });
        const parts = [
            '<div class="info-popup-title">' + esc(title) + (info.species ? ' <span class="info-species">' + esc(info.species) + '</span>' : '') + '</div>',
            '<div class="info-popup-desc">' + esc(info.desc) + '</div>',
        ];
        if (info.bean_size) parts.push('<div class="info-popup-meta"><strong>Bean Size:</strong> ' + esc(info.bean_size) + '</div>');
        if (info.optimal_altitude) parts.push('<div class="info-popup-meta"><strong>Altitude:</strong> ' + esc(resolveAltitude(info.optimal_altitude)) + '</div>');
        popup.innerHTML = parts.join('');
        popup.insertBefore(closeBtn, popup.firstChild);
        el.parentNode.style.position = 'relative';
        el.parentNode.appendChild(popup);
        activePopup = popup;
        popupOpenedAt = Date.now();
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
                label.removeAttribute('for');
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
                label.removeAttribute('for');
                label.classList.add('info-link');
                label.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    showRoastGuide();
                });
            }
            if (select.name === 'bean_size') {
                label.removeAttribute('for');
                label.classList.add('info-link');
                label.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    showBeanSizeGuide();
                });
            }
        });

        // Variety input — make label tappable for variety info popup
        var varietyInput = document.getElementById('variety');
        if (varietyInput) {
            var wrapper = varietyInput.closest('.field');
            if (wrapper) {
                var label = wrapper.querySelector('label');
                if (label) {
                    label.removeAttribute('for');  // prevent focusing the input on tap
                    label.classList.add('info-link');
                    label.addEventListener('pointerdown', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        var val = varietyInput.value.trim();
                        var info = getInfo('varieties', val);
                        if (info) showPopup(label, info, val);
                        else closePopup();
                    });
                }
            }
        }

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
        setTimeout(function() {
            overlay.addEventListener('pointerdown', function() { closePopup(); });
        }, 100);
        document.body.appendChild(overlay);
        activePopup = overlay;
        popupOpenedAt = Date.now();
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
        setTimeout(function() {
            overlay.addEventListener('pointerdown', function() { closePopup(); });
        }, 100);
        document.body.appendChild(overlay);
        activePopup = overlay;
        popupOpenedAt = Date.now();
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

    // Close popup on outside tap (click, not pointerdown — so scrolling doesn't dismiss)
    // Guard: ignore clicks within 300ms of opening (same tap that opened the popup)
    document.addEventListener('click', e => {
        if (activePopup && (Date.now() - popupOpenedAt) > 300 && !activePopup.contains(e.target) && !e.target.classList.contains('info-icon') && !e.target.classList.contains('info-link') && !e.target.classList.contains('info-popup-close')) {
            closePopup();
        }
    });
})();
