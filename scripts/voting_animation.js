(() => {
    const entries = __ENTRIES__;
    const flightMs = __FLIGHT_MS__;
    const staggerMs = __STAGGER_MS__;
    const cleanupMs = __CLEANUP_MS__;
    const launchDelayMs = __LAUNCH_DELAY_MS__;
    const badgeEarlyOffsetMs = __BADGE_EARLY_OFFSET_MS__;
    const doc = window.parent.document;
    const old = doc.getElementById('alc-parent-fly-layer');
    if (old) old.remove();
    const oldStyle = doc.getElementById('alc-parent-fly-style');
    if (oldStyle) oldStyle.remove();

    const style = doc.createElement('style');
    style.id = 'alc-parent-fly-style';
    style.textContent = `
        #alc-parent-fly-layer { position: fixed; inset: 0; pointer-events: none; overflow: visible; z-index: 2147483647; }
        .alc-parent-fly-ball {
            position: fixed; left: var(--start-x); top: var(--start-y);
            width: 38px; height: 38px; border-radius: 999px;
            background: radial-gradient(circle at 35% 30%, var(--alc-flying-ball-light) 0%, var(--alc-flying-ball-mid) 45%, var(--alc-flying-ball-dark) 100%);
            color: var(--alc-flying-ball-text); display: flex; align-items: center; justify-content: center;
            font-size: 14px; font-weight: 900; border: 1px solid rgba(255,225,120,0.70);
            box-shadow: inset 0 1px 3px rgba(255,255,255,0.32), 0 0 16px rgba(255,204,60,0.45), 0 5px 13px rgba(0,0,0,0.42);
            opacity: 0; transform: translate(-50%, -50%) scale(0.72);
            animation: alc-parent-fly-to-country var(--flight) cubic-bezier(0.18, 0.76, 0.28, 1.00) var(--delay) both;
        }
        @keyframes alc-parent-fly-to-country {
            0% { opacity: 0; left: var(--start-x); top: var(--start-y); transform: translate(-50%, -50%) scale(0.72); }
            10% { opacity: 1; }
            70% { opacity: 1; left: var(--end-x); top: var(--end-y); transform: translate(-50%, -50%) scale(1.08); }
            92% { opacity: 1; left: var(--end-x); top: var(--end-y); transform: translate(-50%, -50%) scale(0.62); }
            100% { opacity: 0; left: var(--end-x); top: var(--end-y); transform: translate(-50%, -50%) scale(0.40); }
        }
    `;
    doc.head.appendChild(style);
    const layer = doc.createElement('div');
    layer.id = 'alc-parent-fly-layer';
    doc.body.appendChild(layer);

    function getPointBubbleCenter(pointValue) {
        // Ambil posisi FISIK bubble aslinya di point-pad kanan.
        // Bahkan kalau bubble sudah kosong setelah reveal, data-point tetap ada,
        // jadi bola tetap lahir dari lokasi asal point itu.
        const selector = `.point-pad .point-bubble[data-point=\"${pointValue}\"]`;
        let target = doc.querySelector(selector);

        if (!target) {
            const bubbles = Array.from(doc.querySelectorAll('.point-pad .point-bubble'));
            target = bubbles.find(el => (el.textContent || '').trim() === String(pointValue));
        }

        if (target) {
            const r = target.getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }

        // Fallback relatif ke point-pad, bukan dari atas layar.
        const pad = doc.querySelector('.point-pad');
        if (pad) {
            const pr = pad.getBoundingClientRect();
            const order = [1,2,3,4,5,6,7,8,10,12,14,17,20];
            const idx = Math.max(0, order.indexOf(Number(pointValue)));
            const col = idx <= 6 ? idx : idx - 7;
            const row = idx <= 6 ? 0 : 1;
            return { x: pr.left + 14.5 + col * 37, y: pr.top + 14.5 + row * 39 };
        }

        return { x: window.innerWidth * 0.89, y: window.innerHeight * 0.86 };
    }
    function norm(value) {
        return String(value || '').trim().toUpperCase();
    }

    function getCountryTarget(country, slot) {
        // Target utama: cari pad negara yang BENAR-BENAR sedang tampil di iframe scoreboard.
        // Tidak pakai koordinat kira-kira, jadi landing ke row negara tujuan.
        const wanted = norm(country);

        // Preferred path: st.html renders the scoreboard directly in the
        // Streamlit page, so no iframe coordinate translation is needed.
        const nativePads = Array.from(
            doc.querySelectorAll('#alc-scoreboard-root .moving-pad[data-country]')
        );
        const nativeTarget = nativePads.find(
            el => norm(el.getAttribute('data-country')) === wanted
        );
        if (nativeTarget) {
            const tr = nativeTarget.getBoundingClientRect();
            return {
                x: tr.left + (tr.width * 0.72),
                y: tr.top + (tr.height * 0.50)
            };
        }

        // Backward-compatible iframe fallback.
        const frames = Array.from(doc.querySelectorAll('iframe'));

        for (const frame of frames) {
            try {
                const fdoc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
                if (!fdoc) continue;

                const pads = Array.from(fdoc.querySelectorAll('.moving-pad[data-country]'));
                const target = pads.find(el => norm(el.getAttribute('data-country')) === wanted);
                if (!target) continue;

                const fr = frame.getBoundingClientRect();
                const tr = target.getBoundingClientRect();
                return {
                    // landing di bagian tengah kanan pad: terasa masuk ke negaranya, bukan nyasar ke judul
                    x: fr.left + tr.left + (tr.width * 0.72),
                    y: fr.top + tr.top + (tr.height * 0.50)
                };
            } catch (e) {
                // Abaikan iframe lain yang tidak bisa diakses.
            }
        }

        // Fallback kalau iframe belum kebaca: tetap ke area scoreboard, bukan ke atas judul.
        const col = Math.floor(slot / 10);
        const row = slot % 10;
        const frame = frames[0];
        if (frame) {
            const fr = frame.getBoundingClientRect();
            return { x: fr.left + 82 + col * 286 + 170, y: fr.top + 29 + row * 63 + 19 };
        }
        return { x: window.innerWidth * 0.18, y: window.innerHeight * 0.38 };
    }
    setTimeout(() => {
        entries.forEach((entry, i) => {
            const pts = Number(entry.Points || 0);
            const slot = Number(entry.Slot || 0);
            const country = String(entry.Recipient || '');
            const start = getPointBubbleCenter(pts);
            const end = getCountryTarget(country, slot);
            const ball = doc.createElement('div');
            ball.className = 'alc-parent-fly-ball';
            ball.textContent = String(pts);
            ball.style.setProperty('--start-x', `${start.x}px`);
            ball.style.setProperty('--start-y', `${start.y}px`);
            ball.style.setProperty('--end-x', `${end.x}px`);
            ball.style.setProperty('--end-y', `${end.y}px`);
            ball.style.setProperty('--delay', `${i * staggerMs}ms`);
            ball.style.setProperty('--flight', `${flightMs}ms`);
            layer.appendChild(ball);
        });
    }, launchDelayMs);
    function setCountryScoreAfterLanding(country, pointsValue, delayMs) {
        const wanted = norm(country);
        setTimeout(() => {
            const nativePads = Array.from(
                doc.querySelectorAll('#alc-scoreboard-root .moving-pad[data-country]')
            );
            const nativePad = nativePads.find(
                el => norm(el.getAttribute('data-country')) === wanted
            );
            if (nativePad) {
                const box = nativePad.querySelector('.points-box');
                if (box) {
                    const finalVal = box.getAttribute('data-final-points');
                    if (finalVal !== null && finalVal !== '') {
                        box.textContent = finalVal;
                        box.classList.remove('points-landed');
                        void box.offsetWidth;
                        box.classList.add('points-landed');
                    }
                }
                return;
            }

            const frames = Array.from(doc.querySelectorAll('iframe'));
            for (const frame of frames) {
                try {
                    const fdoc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
                    if (!fdoc) continue;
                    const pads = Array.from(fdoc.querySelectorAll('.moving-pad[data-country]'));
                    const pad = pads.find(el => norm(el.getAttribute('data-country')) === wanted);
                    if (!pad) continue;
                    const box = pad.querySelector('.points-box');
                    if (!box) continue;
                    const finalVal = box.getAttribute('data-final-points');
                    if (finalVal !== null && finalVal !== '') {
                        box.textContent = finalVal;
                        box.classList.remove('points-landed');
                        void box.offsetWidth;
                        box.classList.add('points-landed');
                    }
                    return;
                } catch (e) {}
            }
        }, Math.max(0, delayMs));
    }

    entries.forEach((entry, i) => {
        const pts = Number(entry.Points || 0);
        const country = String(entry.Recipient || '');
        setCountryScoreAfterLanding(country, pts, launchDelayMs + (i * staggerMs) + flightMs - badgeEarlyOffsetMs);
    });

    setTimeout(() => {
        const liveLayer = doc.getElementById('alc-parent-fly-layer');
        if (liveLayer) liveLayer.remove();
        const liveStyle = doc.getElementById('alc-parent-fly-style');
        if (liveStyle) liveStyle.remove();
    }, cleanupMs);
})();