(function() {
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
            "East Timor","Australia","Sumatra","Java","Sulawesi"
        ],
        origin_city: [],
        origin_producer: [],
        process: [
            "Washed","Natural","Honey","Anaerobic","Carbonic Maceration",
            "Wet Hulled","Semi-Washed","Black Honey","Red Honey","Yellow Honey",
            "White Honey","Double Washed","Swiss Water","Lactic Process"
        ],
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

    // Merge values from existing DB entries
    fetch('/api/autocomplete')
        .then(r => r.json())
        .then(dbData => {
            for (const key in dbData) {
                if (DATA[key] !== undefined) {
                    mergeUnique(DATA[key], dbData[key]);
                }
            }
        })
        .catch(() => {});

    let activeDropdown = null;
    const registry = {}; // inputId -> { dropdown, dataKey }

    function createDropdown(input) {
        const list = document.createElement('div');
        list.className = 'ac-dropdown hidden';
        input.parentNode.appendChild(list);
        return list;
    }

    function filterAndShow(input, dropdown, dataKey) {
        const val = input.value.toLowerCase().trim();
        const items = DATA[dataKey] || [];

        if (!val) {
            dropdown.classList.add('hidden');
            return;
        }

        const startsWith = items.filter(i => i.toLowerCase().startsWith(val));
        const contains = items.filter(i =>
            !i.toLowerCase().startsWith(val) && i.toLowerCase().includes(val)
        );
        const matches = [...startsWith, ...contains].slice(0, 8);

        if (matches.length === 0 || (matches.length === 1 && matches[0].toLowerCase() === val)) {
            dropdown.classList.add('hidden');
            return;
        }

        dropdown.innerHTML = matches.map(m => {
            const idx = m.toLowerCase().indexOf(val);
            const before = m.slice(0, idx);
            const bold = m.slice(idx, idx + val.length);
            const after = m.slice(idx + val.length);
            return `<div class="ac-item">${before}<strong>${bold}</strong>${after}</div>`;
        }).join('');

        dropdown.classList.remove('hidden');
        activeDropdown = dropdown;

        dropdown.querySelectorAll('.ac-item').forEach(item => {
            item.addEventListener('pointerdown', e => {
                e.preventDefault();
                e.stopPropagation();
                if (window.coffeeKbd) window.coffeeKbd.suppressDismiss();
                input.value = item.textContent;
                if (window.coffeeKbd) window.coffeeKbd.setInput(item.textContent);
                dropdown.classList.add('hidden');
                activeDropdown = null;
            });
        });
    }

    function setupAutocomplete(inputId, dataKey) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const dropdown = createDropdown(input);
        registry[inputId] = { input, dropdown, dataKey };

        // Also listen for native input events (physical keyboard fallback)
        input.addEventListener('input', () => filterAndShow(input, dropdown, dataKey));
    }

    // Hook into virtual keyboard changes directly
    function waitForKeyboard() {
        if (window.coffeeKbd && window.coffeeKbd.onChange) {
            window.coffeeKbd.onChange((activeInput, value) => {
                // Find which autocomplete field is active
                for (const id in registry) {
                    if (registry[id].input === activeInput) {
                        filterAndShow(activeInput, registry[id].dropdown, registry[id].dataKey);
                        return;
                    }
                }
            });
        } else {
            setTimeout(waitForKeyboard, 50);
        }
    }
    waitForKeyboard();

    // Close dropdowns on outside tap
    document.addEventListener('pointerdown', e => {
        if (activeDropdown && !e.target.closest('.ac-dropdown')) {
            activeDropdown.classList.add('hidden');
            activeDropdown = null;
        }
    });

    setupAutocomplete('roaster', 'roaster');
    setupAutocomplete('origin_country', 'origin_country');
    setupAutocomplete('origin_city', 'origin_city');
    setupAutocomplete('origin_producer', 'origin_producer');
    setupAutocomplete('variety', 'variety');

})();
