(function() {
    let activeInput = null;
    const kbdWrap = document.getElementById('keyboard');

    const kbd = new SimpleKeyboard.default({
        onChange: value => {
            if (activeInput) {
                activeInput.value = value;
                activeInput.dispatchEvent(new Event('input'));
            }
        },
        onKeyPress: button => {
            if (button === '{shift}' || button === '{lock}') {
                const isShift = kbd.options.layoutName !== 'shift';
                kbd.setOptions({ layoutName: isShift ? 'shift' : 'default' });
            } else if (button === '{numbers}') {
                kbd.setOptions({ layoutName: 'numbers' });
            } else if (button === '{abc}') {
                kbd.setOptions({ layoutName: 'default' });
            } else if (button === '{done}') {
                hideKeyboard();
            }
        },
        layout: {
            'default': [
                'q w e r t y u i o p',
                'a s d f g h j k l',
                '{shift} z x c v b n m {backspace}',
                '{numbers} , {space} . {done}'
            ],
            'shift': [
                'Q W E R T Y U I O P',
                'A S D F G H J K L',
                '{lock} Z X C V B N M {backspace}',
                '{numbers} , {space} . {done}'
            ],
            'numbers': [
                '1 2 3 4 5 6 7 8 9 0',
                '- / : ; ( ) & @ "',
                '{abc} . , ? ! \' {backspace}',
                '{abc} {space} . {done}'
            ]
        },
        display: {
            '{backspace}': '⌫',
            '{shift}': '⇧',
            '{lock}': '⇧',
            '{space}': ' ',
            '{done}': 'Done',
            '{numbers}': '123',
            '{abc}': 'ABC'
        },
        theme: 'hg-theme-default hg-layout-default coffee-kbd',
        mergeDisplay: true
    });

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
        if (!kbdWrap.contains(e.target) && !e.target.matches('input')) {
            hideKeyboard();
        }
    });
})();
