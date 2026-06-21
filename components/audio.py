import json

import streamlit.components.v1 as components


BGM_ELEMENT_ID = "alc-global-bgm"
BGM_STATE_ID = "alc-global-bgm-state"
BGM_FADE_IN_MS = 2600
BGM_FADE_OUT_MS = 3200
BGM_LOOP_GAP_MS = 3000
BGM_TARGET_VOLUME = 0.72


def render_bgm_controller(action, backsound_uri, clean_text_func):
    """Control one persistent audio element in the parent Streamlit document.

    action:
      start   -> begin/resume music, fade in, then repeat with a 3-second gap
      fadeout -> fade away and stop for Final Standing
      reset   -> stop, rewind, and remove the player on the landing screen

    Nothing is rendered when no backsound was uploaded.
    """
    if not backsound_uri:
        return

    safe_src = json.dumps(backsound_uri)
    safe_action = json.dumps(clean_text_func(action).lower())
    components.html(
        f"""
        <script>
        (() => {{
            const doc = window.parent.document;
            const win = window.parent;
            const audioId = {json.dumps(BGM_ELEMENT_ID)};
            const stateKey = {json.dumps(BGM_STATE_ID)};
            const src = {safe_src};
            const action = {safe_action};
            const fadeInMs = {int(BGM_FADE_IN_MS)};
            const fadeOutMs = {int(BGM_FADE_OUT_MS)};
            const loopGapMs = {int(BGM_LOOP_GAP_MS)};
            const targetVolume = {float(BGM_TARGET_VOLUME)};

            if (!win[stateKey]) {{
                win[stateKey] = {{
                    fadeTimer: null,
                    gapTimer: null,
                    retryBound: false,
                    desiredAction: 'reset'
                }};
            }}
            const state = win[stateKey];
            state.desiredAction = action;

            function clearTimers() {{
                if (state.fadeTimer) {{ clearInterval(state.fadeTimer); state.fadeTimer = null; }}
                if (state.gapTimer) {{ clearTimeout(state.gapTimer); state.gapTimer = null; }}
            }}

            function getAudio() {{
                let audio = doc.getElementById(audioId);
                if (!audio) {{
                    audio = doc.createElement('audio');
                    audio.id = audioId;
                    audio.preload = 'auto';
                    audio.loop = false;
                    audio.style.display = 'none';
                    doc.body.appendChild(audio);
                }}
                if (audio.src !== src) {{
                    audio.src = src;
                    audio.load();
                }}
                return audio;
            }}

            function fadeTo(audio, destination, durationMs, onDone) {{
                if (state.fadeTimer) {{ clearInterval(state.fadeTimer); state.fadeTimer = null; }}
                const from = Number.isFinite(audio.volume) ? audio.volume : 0;
                const started = performance.now();
                state.fadeTimer = setInterval(() => {{
                    const elapsed = performance.now() - started;
                    const progress = Math.min(1, elapsed / Math.max(1, durationMs));
                    audio.volume = Math.max(0, Math.min(1, from + ((destination - from) * progress)));
                    if (progress >= 1) {{
                        clearInterval(state.fadeTimer);
                        state.fadeTimer = null;
                        if (onDone) onDone();
                    }}
                }}, 45);
            }}

            function bindEnded(audio) {{
                if (audio.dataset.alcEndedBound === '1') return;
                audio.dataset.alcEndedBound = '1';
                audio.addEventListener('ended', () => {{
                    clearTimers();
                    audio.pause();
                    audio.currentTime = 0;
                    audio.volume = 0;
                    if (state.desiredAction !== 'start') return;
                    state.gapTimer = setTimeout(() => {{
                        if (state.desiredAction !== 'start') return;
                        audio.currentTime = 0;
                        audio.volume = 0;
                        const playPromise = audio.play();
                        if (playPromise && playPromise.catch) playPromise.catch(() => {{}});
                        fadeTo(audio, targetVolume, fadeInMs);
                    }}, loopGapMs);
                }});
            }}

            function startAudio() {{
                clearTimers();
                const audio = getAudio();
                bindEnded(audio);
                audio.volume = Math.min(audio.volume || 0, targetVolume);
                const playPromise = audio.play();
                if (playPromise && playPromise.then) {{
                    playPromise.then(() => fadeTo(audio, targetVolume, fadeInMs)).catch(() => {{
                        // Some browsers only allow audio after a direct user gesture.
                        // Retry once on the next click anywhere in the app.
                        if (!state.retryBound) {{
                            state.retryBound = true;
                            const retry = () => {{
                                state.retryBound = false;
                                doc.removeEventListener('click', retry, true);
                                if (state.desiredAction === 'start') startAudio();
                            }};
                            doc.addEventListener('click', retry, true);
                        }}
                    }});
                }}
            }}

            function fadeOutAudio() {{
                clearTimers();
                const audio = doc.getElementById(audioId);
                if (!audio) return;
                fadeTo(audio, 0, fadeOutMs, () => {{
                    audio.pause();
                    audio.currentTime = 0;
                }});
            }}

            function resetAudio() {{
                clearTimers();
                const audio = doc.getElementById(audioId);
                if (audio) {{
                    audio.pause();
                    audio.currentTime = 0;
                    audio.volume = 0;
                    audio.remove();
                }}
            }}

            if (action === 'start') startAudio();
            else if (action === 'fadeout') fadeOutAudio();
            else resetAudio();
        }})();
        </script>
        """,
        height=0,
        scrolling=False,
    )
