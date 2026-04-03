(function() {
    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    const DATA = {
        roaster: [],
        origin_country: [
            "Brazil","Colombia","Ethiopia","Guatemala","Honduras","Costa Rica",
            "Kenya","Indonesia","Mexico","Peru","El Salvador","Nicaragua",
            "Tanzania","Rwanda","Burundi","Uganda","Panama","Bolivia",
            "India","Yemen","Jamaica","Hawaii","Papua New Guinea","Myanmar",
            "Thailand","Vietnam","China","Laos","Philippines","Ecuador",
            "Dominican Republic","Haiti","Cuba","Congo","Malawi","Zambia",
            "Zimbabwe","Cameroon","Ivory Coast","Madagascar","Nepal",
            "East Timor","Australia"
        ],
        origin_city: [],
        origin_producer: [],
        variety: []
    };

    function mergeUnique(existing, incoming) {
        const seen = new Set(existing.map(s => s.toLowerCase()));
        incoming.forEach(val => {
            if (!seen.has(val.toLowerCase())) {
                existing.push(val);
                seen.add(val.toLowerCase());
            }
        });
    }

    fetch('/static/varieties.json')
        .then(r => r.json())
        .then(list => mergeUnique(DATA.variety, list))
        .catch(() => {});

    fetch('/api/autocomplete')
        .then(r => r.json())
        .then(dbData => {
            for (const key in dbData) {
                if (DATA[key] !== undefined) mergeUnique(DATA[key], dbData[key]);
            }
        })
        .catch(() => {});

    const registry = {};

    function createSugBox(input) {
        const box = document.createElement('div');
        box.className = 'ac-sugbox';
        // Put inside the .field so absolute positioning works
        const field = input.closest('.field');
        if (field) {
            field.appendChild(box);
            box._field = field;
        } else {
            input.parentNode.appendChild(box);
        }
        // Event delegation - set up once
        box.addEventListener('pointerdown', e => {
            const el = e.target.closest('.ac-chip');
            if (!el) return;
            e.preventDefault();
            e.stopPropagation();
            if (window.coffeeKbd) window.coffeeKbd.suppressDismiss();
            input.value = el.textContent;
            if (window.coffeeKbd) window.coffeeKbd.setInput(el.textContent);
            box.innerHTML = '';
            if (box._field) box._field.classList.remove('ac-active');
        });
        return box;
    }

    function updateSuggestions(input, box, dataKey) {
        const val = input.value.toLowerCase().trim();
        const items = DATA[dataKey] || [];

        if (!val) { box.innerHTML = ''; if (box._field) box._field.classList.remove('ac-active'); return; }

        const startsWithMatches = items.filter(i => i.toLowerCase().startsWith(val));
        const containsMatches = items.filter(i => !i.toLowerCase().startsWith(val) && i.toLowerCase().includes(val));
        const matches = [...startsWithMatches, ...containsMatches].slice(0, 6);

        if (matches.length === 0 || (matches.length === 1 && matches[0].toLowerCase() === val)) {
            box.innerHTML = '';
            if (box._field) box._field.classList.remove('ac-active');
            return;
        }

        if (box._field) box._field.classList.add('ac-active');
        box.innerHTML = matches.map(m => {
            const idx = m.toLowerCase().indexOf(val);
            const before = m.slice(0, idx);
            const bold = m.slice(idx, idx + val.length);
            const after = m.slice(idx + val.length);
            return `<span class="ac-chip">${esc(before)}<strong>${esc(bold)}</strong>${esc(after)}</span>`;
        }).join('');
    }

    function setupAutocomplete(inputId, dataKey) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const box = createSugBox(input);
        registry[inputId] = { input, box, dataKey };
        input.addEventListener('input', () => updateSuggestions(input, box, dataKey));
    }

    // Hook into virtual keyboard
    /**
     * Poll for the virtual keyboard API (window.coffeeKbd) which may load after this script.
     * Retries up to 100 times at 50ms intervals (5 seconds total).
     */
    function waitForKeyboard(retries) {
        if (retries === undefined) retries = 100;
        if (window.coffeeKbd && window.coffeeKbd.onChange) {
            window.coffeeKbd.onChange((activeInput, value) => {
                for (const id in registry) {
                    if (registry[id].input === activeInput) {
                        updateSuggestions(activeInput, registry[id].box, registry[id].dataKey);
                        return;
                    }
                }
            });
        } else if (retries > 0) {
            setTimeout(() => waitForKeyboard(retries - 1), 50);
        }
    }
    waitForKeyboard();

    setupAutocomplete('roaster', 'roaster');
    setupAutocomplete('origin_country', 'origin_country');
    setupAutocomplete('origin_city', 'origin_city');
    setupAutocomplete('origin_producer', 'origin_producer');
    setupAutocomplete('variety', 'variety');
})();
