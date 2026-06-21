(function() {
    const doc = window.parent.document;
    const old = doc.getElementById('alc-temporary-button-lock');
    if (old) old.remove();
    const style = doc.createElement('style');
    style.id = 'alc-temporary-button-lock';
    style.textContent = `
        div.stButton > button {
            pointer-events: none !important;
            opacity: 0.62 !important;
            filter: grayscale(0.18) brightness(0.92) !important;
            cursor: not-allowed !important;
        }
    `;
    doc.head.appendChild(style);
    setTimeout(() => {
        const s = doc.getElementById('alc-temporary-button-lock');
        if (s) s.remove();
    }, __UNLOCK_MS__);
})();