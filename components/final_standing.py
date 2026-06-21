import html

import streamlit as st
import streamlit.components.v1 as components


def render_final_standing(*, title, host, final_standing_html, home_callback, render_bgm, backsound_uri, clean_text_func, logo_uri=""):

    safe_title = html.escape(clean_text_func(title), quote=True)
    safe_host = html.escape(clean_text_func(host), quote=True)
    logo_html = (
        f'<div class="alc-header-logo-slot">'
        f'<img class="alc-header-logo" src="{logo_uri}" alt="ALC logo">'
        f'</div>'
        if logo_uri
        else ""
    )

    render_bgm("fadeout", backsound_uri, clean_text_func)
    st.button("HOME", key="home_final_standing", on_click=home_callback)
    st.markdown(
        f'''
        <div class="alc-header-row">
            {logo_html}
            <div class="title-wrap">
                <div class="title-shell">
                    <div class="main-title">{safe_title}</div>
                    <div class="title-divider"></div>
                    <div class="host-row">{safe_host}</div>
                </div>
            </div>
        </div>
        ''',
        unsafe_allow_html=True
    )

    components.html(final_standing_html, height=690, scrolling=False)

    st.stop()

