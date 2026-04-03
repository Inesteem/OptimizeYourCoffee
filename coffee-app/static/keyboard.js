(function() {
    let activeInput = null;           // Currently focused input element
    let layoutChanging = false;       // True during layout transitions; prevents stale pointerdown from dismissing keyboard
    let ignoreNextDismiss = false;    // Briefly true after autocomplete selection to prevent keyboard hide
    const kbdWrap = document.getElementById('keyboard');

    const kbd = new SimpleKeyboard.default({
        onChange: value => {
            if (activeInput) {
                // For number inputs, "1." is rejected by the browser — show "1.0" temporarily
                if (activeInput.type === 'number' && value.endsWith('.')) {
                    activeInput.value = value + '0';
                } else {
                    activeInput.value = value;
                }
                activeInput.dispatchEvent(new Event('input', { bubbles: true }));
                changeListeners.forEach(fn => fn(activeInput, value));
            }
        },
        onKeyPress: button => {
            if (button === '{shift}' || button === '{lock}') {
                const isShift = kbd.options.layoutName !== 'shift';
                switchLayout(isShift ? 'shift' : 'default');
            } else if (kbd.options.layoutName === 'shift' && button !== '{backspace}' && !button.startsWith('{')) {
                // Auto-return to lowercase after one character
                switchLayout('default');
            } else if (button === '{numbers}') {
                switchLayout('numbers');
            } else if (button === '{abc}') {
                switchLayout('default');
            } else if (button === '{special}') {
                switchLayout('special');
            } else if (kbd.options.layoutName === 'special' && !button.startsWith('{')) {
                // Auto-return to default after typing one special char
                switchLayout('default');
            } else if (button === '{done}') {
                hideKeyboard();
            }
        },
        layout: {
            'default': [
                'q w e r t y u i o p ü',
                'a s d f g h j k l ö ä',
                '{shift} z x c v b n m {backspace}',
                '{numbers} {special} , {space} . {done}'
            ],
            'shift': [
                'Q W E R T Y U I O P Ü',
                'A S D F G H J K L Ö Ä',
                '{lock} Z X C V B N M {backspace}',
                '{numbers} {special} , {space} . {done}'
            ],
            'numbers': [
                '1 2 3 4 5 6 7 8 9 0',
                '- / : ; ( ) & @ "',
                '{abc} . , ? ! \' {backspace}',
                '{abc} {space} . {done}'
            ],
            'special': [
                'ä ö ü ß à á â ã å æ',
                'è é ê ë ì í î ï ñ ò',
                'ó ô õ ø ù ú û ý ç ð',
                '{abc} , {space} . {done}'
            ]
        },
        display: {
            '{backspace}': '⌫',
            '{shift}': '⇧',
            '{lock}': '⇧',
            '{space}': ' ',
            '{done}': 'Done',
            '{numbers}': '123',
            '{abc}': 'ABC',
            '{special}': 'àü'
        },
        theme: 'hg-theme-default hg-layout-default coffee-kbd',
        mergeDisplay: true
    });

    // Expose for autocomplete/chips to sync state and get change notifications
    const changeListeners = [];
    window.coffeeKbd = {
        setInput: val => kbd.setInput(val),
        suppressDismiss: () => { ignoreNextDismiss = true; setTimeout(() => { ignoreNextDismiss = false; }, 200); },
        onChange: fn => changeListeners.push(fn),
        getActiveInput: () => activeInput
    };

    function switchLayout(name) {
        layoutChanging = true;
        kbd.setOptions({ layoutName: name });
        setTimeout(() => { layoutChanging = false; }, 100);
    }

    function showKeyboard(input) {
        activeInput = input;
        kbd.setInput(input.value);
        if (input.type === 'number') {
            kbd.setOptions({ layoutName: 'numbers' });
        } else {
            kbd.setOptions({ layoutName: 'default' });
        }
        kbdWrap.classList.remove('hidden');
        document.body.classList.add('kbd-open');
        setTimeout(() => input.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
    }

    function hideKeyboard() {
        kbdWrap.classList.add('hidden');
        document.body.classList.remove('kbd-open');
        if (activeInput) activeInput.blur();
        activeInput = null;
    }

    document.querySelectorAll('input[type="text"], input[type="number"]').forEach(input => {
        input.addEventListener('focus', () => showKeyboard(input));
        input.setAttribute('inputmode', 'none');
    });

    document.addEventListener('pointerdown', e => {
        if (layoutChanging || ignoreNextDismiss) return;
        if (e.target.closest('.ac-sugbox') || e.target.closest('.chip-suggestions') || e.target.closest('#emoji-picker')) return;
        if (!kbdWrap.contains(e.target) && !e.target.matches('input')) {
            hideKeyboard();
        }
    });
})();
