import html

import streamlit as st


def render_landing(
    *,
    title,
    host,
    qc_errors,
    qc_warnings,
    qc_passed,
    result_excel_bytes,
    result_excel_filename,
    enter_callback,
    final_callback,
    render_bgm,
    backsound_uri,
    clean_text_func,
):
    """Render the Rehearsal landing actions only.

    Changing the uploaded edition intentionally belongs only to the main
    Select Mode page, so this component never renders that action.
    """
    safe_title = html.escape(clean_text_func(title), quote=True)
    safe_host = html.escape(clean_text_func(host), quote=True)

    render_bgm("reset", backsound_uri, clean_text_func)
    st.markdown(
        f'''
        <div class="welcome-screen">
            <div class="welcome-kicker">WELCOME TO</div>
            <div class="welcome-title">{safe_title}</div>
            <div class="welcome-host">{safe_host}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    if qc_errors:
        st.error(
            f"WORKBOOK QC FAILED — {len(qc_errors)} error(s) must be fixed "
            "before entering the voting arena."
        )
    elif qc_warnings:
        st.warning(
            f"WORKBOOK QC WARNING — {len(qc_warnings)} item(s) need attention. "
            "The voting arena can still be opened."
        )

    if qc_errors or qc_warnings:
        with st.expander("VIEW WORKBOOK QC REPORT", expanded=bool(qc_errors)):
            if qc_errors:
                st.markdown("**Errors — arena entry is blocked**")
                for qc_error in qc_errors:
                    st.write(f"• {qc_error}")

            if qc_warnings:
                st.markdown("**Warnings — the scoreboard can still run**")
                for qc_warning in qc_warnings:
                    st.write(f"• {qc_warning}")

    st.button(
        "ENTER VOTING ARENA",
        key="enter_voting_arena",
        use_container_width=True,
        on_click=enter_callback,
        disabled=not qc_passed,
    )

    st.button(
        "VIEW FINAL STANDING",
        key="view_final_standing_start",
        use_container_width=True,
        on_click=final_callback,
        disabled=not qc_passed,
    )

    st.download_button(
        "DOWNLOAD RESULT",
        data=result_excel_bytes,
        file_name=result_excel_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_result_landing",
        use_container_width=True,
        disabled=not qc_passed,
    )

    st.stop()
