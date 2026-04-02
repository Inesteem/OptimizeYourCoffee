(function() {
    const DATA = {
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
        process: [
            "Washed","Natural","Honey","Anaerobic","Carbonic Maceration",
            "Wet Hulled","Semi-Washed","Black Honey","Red Honey","Yellow Honey",
            "White Honey","Double Washed","Swiss Water","Lactic Process"
        ],
        variety: [] // populated from server
    };

    // Fetch varieties from static JSON
    fetch('/static/varieties.json')
        .then(r => r.json())
        .then(list => { DATA.variety = list; })
        .catch(() => {});

    let activeDropdown = null;

    function createDropdown(input) {
        const wrap = document.createElement('div');
        wrap.className = 'ac-wrap';
        input.parentNode.style.position = 'relative';

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

        // Sort: starts-with first, then contains
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
                input.value = item.textContent;
                input.dispatchEvent(new Event('input'));
                dropdown.classList.add('hidden');
                activeDropdown = null;
            });
        });
    }

    function setupAutocomplete(inputId, dataKey) {
        const input = document.getElementById(inputId);
        if (!input) return;

        const dropdown = createDropdown(input);

        input.addEventListener('input', () => filterAndShow(input, dropdown, dataKey));
        input.addEventListener('focus', () => filterAndShow(input, dropdown, dataKey));
    }

    // Close dropdowns on outside tap
    document.addEventListener('pointerdown', e => {
        if (activeDropdown && !activeDropdown.contains(e.target) &&
            !e.target.matches('.ac-dropdown, .ac-item')) {
            activeDropdown.classList.add('hidden');
            activeDropdown = null;
        }
    });

    // Init
    setupAutocomplete('origin_country', 'origin_country');
    setupAutocomplete('process', 'process');
    setupAutocomplete('variety', 'variety');
})();
