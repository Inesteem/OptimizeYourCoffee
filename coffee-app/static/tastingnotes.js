(function() {
    const NOTES = {
        // Fruits
        "dried apricot":    "🍑",
        "apricot":          "🍑",
        "lemonade":         "🍋",
        "lemon":            "🍋",
        "orange":           "🍊",
        "tangerine":        "🍊",
        "black currant":    "🫐",
        "blackcurrant":     "🫐",
        "blueberry":        "🫐",
        "strawberry":       "🍓",
        "raspberry":        "🍓",
        "cherry":           "🍒",
        "apple":            "🍏",
        "green apple":      "🍏",
        "peach":            "🍑",
        "plum":             "🍇",
        "grape":            "🍇",
        "tropical":         "🍍",
        "pineapple":        "🍍",
        "mango":            "🥭",
        "passionfruit":     "🍈",
        "melon":            "🍈",
        "watermelon":       "🍉",
        "banana":           "🍌",
        "fig":              "🫐",
        "dates":            "🫐",
        "cranberry":        "🫐",
        "grapefruit":       "🍊",
        "lime":             "🍋",
        "citrus":           "🍋",
        "bergamot":         "🍋",

        // Chocolate & nuts
        "cacao nibs":       "🍫",
        "cacao":            "🍫",
        "chocolate":        "🍫",
        "dark chocolate":   "🍫",
        "milk chocolate":   "🍫",
        "cocoa":            "🍫",
        "hazelnut":         "🌰",
        "almond":           "🌰",
        "walnut":           "🌰",
        "peanut":           "🥜",
        "nutty":            "🌰",

        // Sweet
        "honey":            "🍯",
        "caramel":          "🍮",
        "toffee":           "🍮",
        "brown sugar":      "🍮",
        "maple":            "🍁",
        "molasses":         "🍮",
        "vanilla":          "🍦",
        "butterscotch":     "🍮",
        "candy":            "🍬",
        "sugarcane":        "🍬",

        // Floral & herbal
        "jasmine":          "🌸",
        "rose":             "🌹",
        "lavender":         "💜",
        "floral":           "🌺",
        "hibiscus":         "🌺",
        "chamomile":        "🌼",
        "tea":              "🍵",
        "black tea":        "🍵",
        "green tea":        "🍵",
        "earl grey":        "🍵",
        "herbal":           "🌿",
        "mint":             "🌿",
        "basil":            "🌿",

        // Spice
        "cinnamon":         "✨",
        "clove":            "✨",
        "cardamom":         "✨",
        "ginger":           "✨",
        "pepper":           "🌶️",
        "spicy":            "🌶️",
        "nutmeg":           "✨",

        // Other
        "smoky":            "🔥",
        "tobacco":          "🍂",
        "wine":             "🍷",
        "red wine":         "🍷",
        "whiskey":          "🥃",
        "rum":              "🥃",
        "butter":           "🧈",
        "cream":            "🥛",
        "yogurt":           "🥛",
        "cedar":            "🪵",
        "woody":            "🪵",
        "earthy":           "🌍",
        "stone fruit":      "🍑",
        "berry":            "🫐",
        "tropical fruit":   "🍍",
        "dried fruit":      "🍑",
        "nougat":           "🍮"
    };

    // Get all known note names for suggestions
    const ALL_NOTES = [...new Set(Object.keys(NOTES))].sort();

    function getEmoji(note) {
        const key = note.toLowerCase().trim();
        return NOTES[key] || '';
    }

    function initChipInput(container) {
        const hiddenInput = container.querySelector('input[type="hidden"]');
        const chipsWrap = container.querySelector('.chips');
        const textInput = container.querySelector('.chip-text-input');
        const suggestions = container.querySelector('.chip-suggestions');

        // Parse existing value
        let chips = [];
        if (hiddenInput.value) {
            chips = hiddenInput.value.split(',').map(s => s.trim()).filter(Boolean);
        }

        function render() {
            // Clear existing chip elements (keep input)
            chipsWrap.querySelectorAll('.chip').forEach(el => el.remove());

            chips.forEach((note, idx) => {
                const chip = document.createElement('span');
                chip.className = 'chip';
                const emoji = getEmoji(note);
                chip.innerHTML = `${emoji ? emoji + ' ' : ''}${note}<button class="chip-x" data-idx="${idx}">×</button>`;
                chipsWrap.insertBefore(chip, textInput);
            });

            hiddenInput.value = chips.join(', ');
        }

        function addChip(note) {
            note = note.trim();
            if (!note || chips.some(c => c.toLowerCase() === note.toLowerCase())) return;
            chips.push(note);
            render();
            textInput.value = '';
            if (window.coffeeKbd) window.coffeeKbd.setInput('');
            suggestions.classList.add('hidden');
        }

        function showSuggestions(val) {
            val = val.toLowerCase().trim();
            // Filter notes not already added
            const available = ALL_NOTES.filter(n => !chips.some(c => c.toLowerCase() === n));
            let matches;
            if (!val) {
                // Show common defaults when empty
                matches = available.slice(0, 12);
            } else {
                const sw = available.filter(n => n.startsWith(val));
                const co = available.filter(n => !n.startsWith(val) && n.includes(val));
                matches = [...sw, ...co].slice(0, 8);
            }

            if (matches.length === 0) {
                suggestions.classList.add('hidden');
                return;
            }

            suggestions.innerHTML = matches.map(m => {
                const emoji = getEmoji(m);
                return `<div class="chip-sug">${emoji ? emoji + ' ' : ''}${m}</div>`;
            }).join('');
            suggestions.classList.remove('hidden');

            suggestions.querySelectorAll('.chip-sug').forEach(el => {
                el.addEventListener('pointerdown', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (window.coffeeKbd) window.coffeeKbd.suppressDismiss();
                    const text = el.textContent.replace(/^\p{Emoji_Presentation}\s*/u, '').trim();
                    // Extract just the note name (after emoji)
                    const noteText = el.textContent.replace(/^[^\w]*/, '').trim();
                    addChip(noteText || el.textContent.trim());
                });
            });
        }

        // Events
        textInput.addEventListener('input', () => showSuggestions(textInput.value));
        textInput.addEventListener('focus', () => showSuggestions(textInput.value));

        // Remove chip
        chipsWrap.addEventListener('pointerdown', e => {
            const btn = e.target.closest('.chip-x');
            if (btn) {
                e.preventDefault();
                chips.splice(parseInt(btn.dataset.idx), 1);
                render();
            }
        });

        // Initial render
        render();
    }

    // Init all chip inputs on the page
    document.querySelectorAll('.chip-input').forEach(initChipInput);
})();
