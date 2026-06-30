"""
app.py — RFQ Pipeline (with login, role-based access, and email notifications)
Run with:  streamlit run app.py
"""

import streamlit as st
from datetime import datetime
import os

import db
from db import (
    ROLES, STAGES, STAGE_LABEL, STAGE_COLOR, PRIORITY_COLOR, ALLOWED_DOC_EXT,
    RFQ_CREATOR_ROLES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def time_ago(ts_str):
    try:
        ts = datetime.fromisoformat(ts_str)
    except Exception:
        return ""
    diff = datetime.now() - ts
    mins = int(diff.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"


def fmt_date(ts_str):
    try:
        return datetime.fromisoformat(ts_str).strftime("%d %b %Y")
    except Exception:
        return "—"


def initials(name):
    return "".join(w[0] for w in name.split()).upper()[:2]


def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap');

    /* ---- Professional blue corporate theme ---- */
    /* Ink:    #0F2A4A  (deep navy - headings, primary text)        */
    /* Brand:  #1B5FA8  (corporate blue - primary actions, accents) */
    /* Steel:  #5B7088  (muted blue-grey - secondary text)          */
    /* Paper:  #F4F7FB  (cool off-white page background)            */
    /* Line:   #DCE3EC  (borders)                                   */

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: #F4F7FB; }

    /* Force readable text colors regardless of the browser/OS theme */
    .stApp, .stApp p, .stApp span, .stApp label, .stApp div { color: #0F2A4A; }
    .stMarkdown, .stMarkdown p { color: #0F2A4A; }
    [data-testid="stCaptionContainer"] { color: #5B7088 !important; }

    h1, h2, h3 { font-family: 'Fraunces', Georgia, serif !important; color: #0F2A4A !important; }

    .rfq-eyebrow { font-size: 11px; font-weight: 700; color: #1B5FA8; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 2px; }

    .rfq-card { background: #fff; border: 1px solid #DCE3EC; border-radius: 11px; padding: 14px 16px; margin-bottom: 10px; }
    .rfq-card-code { font-size: 10.5px; font-weight: 700; color: #8FA0B5; letter-spacing: 0.03em; }
    .rfq-card-title { font-size: 14px; font-weight: 700; color: #0F2A4A; margin: 3px 0 2px; line-height: 1.35; }
    .rfq-card-client { font-size: 12.5px; color: #5B7088; margin-bottom: 8px; }
    .rfq-card-meta { font-size: 11.5px; color: #5B7088; }

    .rfq-badge { display: inline-flex; align-items: center; gap: 5px; padding: 4px 11px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    .rfq-chip { display: inline-flex; align-items: center; gap: 5px; background: #fff; border: 1px solid #DCE3EC; border-radius: 999px; padding: 3px 10px; font-size: 12px; color: #0F2A4A; margin: 2px 4px 2px 0; }
    .rfq-dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:5px; }

    .rfq-stat-box { background: #fff; border: 1px solid #DCE3EC; border-radius: 9px; padding: 10px 14px; text-align: center; }
    .rfq-stat-label { font-size: 10.5px; font-weight: 700; color: #5B7088; text-transform: uppercase; letter-spacing: 0.04em; }
    .rfq-stat-value { font-size: 20px; font-weight: 700; color: #0F2A4A; }

    .rfq-timeline-item { display:flex; gap:10px; padding-bottom:12px; }
    .rfq-timeline-dot { width:8px; height:8px; border-radius:50%; margin-top:4px; flex-shrink:0; }
    .rfq-timeline-note { font-size:12.5px; color:#0F2A4A; line-height:1.5; }
    .rfq-timeline-meta { font-size:11px; color:#8FA0B5; margin-top:2px; }

    /* Buttons: primary = corporate blue, secondary = outlined */
    .stButton button { border-radius: 8px !important; font-weight: 600 !important; font-size: 13px !important; }
    .stButton button[kind="primary"] {
        background-color: #1B5FA8 !important; border-color: #1B5FA8 !important; color: #fff !important;
    }
    .stButton button[kind="primary"]:hover { background-color: #154B85 !important; border-color: #154B85 !important; }
    .stButton button[kind="secondary"] {
        background-color: #fff !important; border: 1px solid #DCE3EC !important; color: #0F2A4A !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab"] { color: #5B7088; font-weight: 600; }
    .stTabs [aria-selected="true"] { color: #1B5FA8 !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: #1B5FA8 !important; }

    /* Inputs */
    .stTextInput input, .stNumberInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        border-radius: 8px !important;
    }

    /* Containers / bordered boxes */
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 12px !important; border-color: #DCE3EC !important; }

    .role-pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:11px; font-weight:700; }
    </style>
    """, unsafe_allow_html=True)


def badge_html(stage_id, size="md"):
    label = STAGE_LABEL[stage_id]
    color = STAGE_COLOR[stage_id]
    pad = "3px 9px" if size == "sm" else "4px 11px"
    return (f'<span class="rfq-badge" style="color:{color};background:{color}14;'
            f'border:1px solid {color}33;padding:{pad}">{label}</span>')


def role_pill_html(role):
    info = ROLES.get(role, {"label": role, "color": "#5B7088"})
    return f'<span class="role-pill" style="background:{info["color"]}14;color:{info["color"]}">{info["label"]}</span>'


def person_chip_html(user_id):
    u = db.get_user_by_id(user_id)
    if not u:
        return ""
    color = ROLES.get(u["role"], {}).get("color", "#5B7088")
    return (f'<span class="rfq-chip"><span style="width:16px;height:16px;border-radius:50%;'
            f'background:{color};color:#fff;font-size:8.5px;font-weight:700;display:inline-flex;'
            f'align-items:center;justify-content:center">{initials(u["full_name"])}</span>{u["full_name"]}</span>')


# ---------------------------------------------------------------------------
# Auth screens
# ---------------------------------------------------------------------------

def render_login():
    st.markdown('<div class="rfq-eyebrow">QUOTING DESK</div>', unsafe_allow_html=True)
    st.markdown("## Sign in to RFQ Pipeline")
    st.write("")
    col1, col2 = st.columns([1, 1])
    with col1:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if submitted:
                user = db.authenticate(username, password)
                if user:
                    st.session_state.user = user
                    st.session_state.active_role = user["roles"][0] if user["roles"] else None
                    st.rerun()
                else:
                    st.error("Invalid username or password, or the account is inactive.")
        st.caption(
            f"First time here? Default admin login is **{db.DEFAULT_ADMIN_USERNAME}** / "
            f"**{db.DEFAULT_ADMIN_PASSWORD}** — change the password right after signing in."
        )


def render_logout_bar():
    user = st.session_state.user
    has_multiple_roles = len(user["roles"]) > 1

    if has_multiple_roles:
        col1, col2, col3 = st.columns([3, 2, 1])
    else:
        col1, col2, col3 = st.columns([5, 0.001, 1])

    with col1:
        st.markdown(
            f"Signed in as **{user['full_name']}** &nbsp; "
            + " ".join(role_pill_html(r) for r in user["roles"]),
            unsafe_allow_html=True
        )
    with col2:
        if has_multiple_roles:
            current_active = st.session_state.get("active_role", user["roles"][0])
            if current_active not in user["roles"]:
                current_active = user["roles"][0]
            chosen = st.selectbox(
                "Acting as", user["roles"],
                index=user["roles"].index(current_active),
                format_func=lambda r: ROLES[r]["label"],
                key="role_switcher", label_visibility="collapsed",
            )
            if chosen != st.session_state.get("active_role"):
                st.session_state.active_role = chosen
                st.rerun()
    with col3:
        if st.button("Sign out", use_container_width=True):
            del st.session_state.user
            st.session_state.pop("active_role", None)
            st.rerun()


# ---------------------------------------------------------------------------
# Admin: user management
# ---------------------------------------------------------------------------

def render_admin_users():
    st.markdown("### User management")
    st.caption("Create accounts and assign roles. Only Admins can access this page.")

    with st.expander("➕ Add new user", expanded=False):
        with st.form("new_user_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                full_name = st.text_input("Full name")
                username = st.text_input("Username (for login)")
            with c2:
                email = st.text_input("Email address")
                roles = st.multiselect("Role(s)", list(ROLES.keys()), format_func=lambda r: ROLES[r]["label"],
                                        help="A user can hold more than one role, e.g. Sales + Pre-Sale.")
            password = st.text_input("Temporary password", type="password",
                                      help="Share this with the user — they can be given a way to change it later.")
            submitted = st.form_submit_button("Create user", type="primary")
            if submitted:
                if not all([full_name.strip(), username.strip(), email.strip(), password]) or not roles:
                    st.error("All fields are required, and at least one role must be selected.")
                else:
                    ok, msg = db.create_user(username, full_name, email, roles, password)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    st.write("")
    st.markdown("**Existing users**")
    users = db.fetch_users()
    for u in users:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            with c1:
                st.markdown(f"**{u['full_name']}**  \n`{u['username']}`")
            with c2:
                st.markdown(u["email"])
                st.markdown(" ".join(role_pill_html(r) for r in u["roles"]) or "—", unsafe_allow_html=True)
            with c3:
                new_roles = st.multiselect("Role(s)", list(ROLES.keys()), default=u["roles"],
                                            format_func=lambda r: ROLES[r]["label"],
                                            key=f"roles_{u['id']}", label_visibility="collapsed")
                active = st.checkbox("Active", value=bool(u["active"]), key=f"active_{u['id']}")
                if set(new_roles) != set(u["roles"]) or bool(active) != bool(u["active"]):
                    if not new_roles:
                        st.warning("A user must have at least one role — change not applied.")
                    else:
                        db.update_user(u["id"], u["full_name"], u["email"], new_roles, active)
                        st.rerun()
            with c4:
                if st.button("Reset PW", key=f"resetpw_{u['id']}", use_container_width=True):
                    st.session_state[f"show_reset_{u['id']}"] = True
                if st.session_state.get(f"show_reset_{u['id']}"):
                    new_pw = st.text_input("New password", type="password", key=f"newpw_{u['id']}")
                    if st.button("Confirm reset", key=f"confirmreset_{u['id']}"):
                        if new_pw:
                            db.reset_password(u["id"], new_pw)
                            st.success("Password reset.")
                            st.session_state[f"show_reset_{u['id']}"] = False
                            st.rerun()


def render_admin_email_settings():
    st.markdown("### Email settings (Gmail SMTP)")
    st.caption(
        "To enable real automatic emails, create a **Gmail App Password**: "
        "Google Account → Security → 2-Step Verification (must be on) → App passwords. "
        "Paste your Gmail address and the 16-character app password below."
    )
    current_email = db.get_setting("smtp_email")
    current_pw = db.get_setting("smtp_app_password")
    configured = bool(current_email) and bool(current_pw)
    if configured:
        st.success(f"Email is configured — sending as **{current_email}**")
    else:
        st.warning("Email is not configured yet. RFQ notifications will be logged but not sent until you set this up.")

    with st.form("email_settings_form"):
        smtp_email = st.text_input("Gmail address", value=current_email, placeholder="you@gmail.com")
        smtp_app_password = st.text_input("Gmail App Password", type="password",
                                           placeholder="16-character app password",
                                           help="This is NOT your regular Gmail password.")
        submitted = st.form_submit_button("Save email settings", type="primary")
        if submitted:
            db.set_setting("smtp_email", smtp_email.strip())
            db.set_setting("smtp_app_password", smtp_app_password.strip())
            st.success("Saved. New RFQ assignments will now trigger real emails.")
            st.rerun()

    st.write("")
    st.markdown("**Recent email log**")
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM email_log ORDER BY sent_at DESC LIMIT 20").fetchall()
    conn.close()
    if not rows:
        st.caption("No emails sent yet.")
    for r in rows:
        icon = "✅" if r["status"] == "sent" else "❌"
        st.markdown(
            f"{icon} **{r['subject']}** → {r['to_email']} &nbsp; "
            f"<span style='color:#8FA0B5;font-size:11px'>{time_ago(r['sent_at'])}</span>"
            + (f"<br><span style='color:#B8453D;font-size:11.5px'>{r['error']}</span>" if r["error"] else ""),
            unsafe_allow_html=True
        )


# ---------------------------------------------------------------------------
# New RFQ form
# ---------------------------------------------------------------------------

def render_new_rfq_form(current_user):
    st.markdown("#### Log a new RFQ")

    man_days_users = db.fetch_users_by_role("man_days_est")
    irm_users = db.fetch_users_by_role("irm_est")
    presale_users = db.fetch_users_by_role("presale")

    missing = []
    if not man_days_users:
        missing.append("Man Days Estimator")
    if not irm_users:
        missing.append("IRM Estimator")
    if not presale_users:
        missing.append("Pre-Sale")
    if missing:
        st.warning(
            "No active users found for role(s): " + ", ".join(missing) +
            ". Ask an Admin to create these users first (Admin → User management)."
        )

    with st.form("new_rfq_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("RFQ name", placeholder="e.g. ERP Integration Module")
        with col2:
            customer = st.text_input("Customer", placeholder="e.g. Alfanar Industries")

        priority = st.selectbox("Priority", ["high", "medium", "low"], index=1)

        st.markdown("**Assign resources**")
        c1, c2, c3 = st.columns(3)
        with c1:
            md_options = {u["full_name"]: u["id"] for u in man_days_users}
            md_choice = st.selectbox("Man Days Estimator", ["—"] + list(md_options.keys()))
        with c2:
            irm_options = {u["full_name"]: u["id"] for u in irm_users}
            irm_choice = st.selectbox("IRM Estimator", ["—"] + list(irm_options.keys()))
        with c3:
            ps_options = {u["full_name"]: u["id"] for u in presale_users}
            ps_choice = st.selectbox("Pre-Sale", ["—"] + list(ps_options.keys()))

        st.markdown("**RFQ documents**")
        uploaded_files = st.file_uploader(
            "Upload one or more files (RFQ, BoM, SOW, etc.)",
            type=ALLOWED_DOC_EXT, accept_multiple_files=True
        )

        submitted = st.form_submit_button("Create RFQ & notify team", type="primary", use_container_width=True)
        if submitted:
            if not name.strip() or not customer.strip():
                st.error("RFQ name and Customer are required.")
            else:
                md_id = md_options.get(md_choice)
                irm_id = irm_options.get(irm_choice)
                ps_id = ps_options.get(ps_choice)

                rfq = db.create_rfq(
                    name.strip(), customer.strip(), priority, current_user,
                    md_id, irm_id, ps_id, uploaded_files or []
                )

                results = db.notify_assigned_resources(rfq)
                sent_ok = [r for r in results if r["ok"]]
                sent_fail = [r for r in results if not r["ok"]]

                st.success(f"RFQ {rfq['code']} created.")
                if sent_ok:
                    st.info("Emails sent to: " + ", ".join(f"{r['user']} ({r['role']})" for r in sent_ok))
                if sent_fail:
                    st.warning(
                        "Could not email: " + ", ".join(f"{r['user']} ({r['role']})" for r in sent_fail) +
                        " — check Admin → Email Settings."
                    )
                st.session_state.show_new_rfq = False
                st.rerun()


# ---------------------------------------------------------------------------
# RFQ detail + stage actions
# ---------------------------------------------------------------------------

def render_files_section(rfq):
    if not rfq["files"]:
        return
    st.markdown("**Documents**")
    kind_labels = {"rfq_doc": "RFQ document", "man_days_file": "Man Days estimate",
                   "irm_file": "IRM estimate", "quote": "Quote file"}
    for f in rfq["files"]:
        label = kind_labels.get(f["kind"], f["kind"])
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(
                f"📎 **{label}** — {f['filename']}  \n"
                f"<span style='font-size:11px;color:#8FA0B5'>uploaded by {f['uploaded_by']} · {time_ago(f['uploaded_at'])}</span>",
                unsafe_allow_html=True
            )
        with col2:
            if os.path.exists(f["stored_path"]):
                with open(f["stored_path"], "rb") as fh:
                    st.download_button("Download", fh.read(), file_name=f["filename"],
                                        key=f"dl_{f['id']}", use_container_width=True)
    st.markdown("---")


def render_rfq_detail(rfq, current_user):
    email_result_key = f"email_result_{rfq['id']}"
    if email_result_key in st.session_state:
        fallback_label, results = st.session_state.pop(email_result_key)
        _report_email_results(results, fallback_label)

    st.markdown(f"<span style='font-size:11.5px;font-weight:700;color:#5B7088'>{rfq['code']}</span>", unsafe_allow_html=True)
    st.markdown(f"### {rfq['name']}")
    st.markdown(f"<span style='font-size:13.5px;color:#5B7088'>{rfq['customer']}</span>", unsafe_allow_html=True)
    pr_color = PRIORITY_COLOR.get(rfq["priority"], "#5B7088")
    st.markdown(
        badge_html(rfq["stage"]) + "&nbsp;&nbsp;" +
        f"<span class='rfq-dot' style='background:{pr_color}'></span>"
        f"<span style='font-size:12px;color:#5B7088'>{rfq['priority'].title()} priority</span>",
        unsafe_allow_html=True
    )
    st.markdown("---")

    render_files_section(rfq)

    if rfq["quote_amount"]:
        st.markdown(
            f"<div style='background:#1B5FA80D;border:1px solid #1B5FA833;border-radius:10px;padding:14px 16px;margin-bottom:14px'>"
            f"<div style='font-size:11px;font-weight:700;color:#1F7A5C;text-transform:uppercase'>Quoted price</div>"
            f"<div style='font-size:22px;font-weight:700;color:#0F2A4A'>${rfq['quote_amount']:,.0f}</div>"
            f"<div style='font-size:12px;color:#5B7088'>Valid until {fmt_date(rfq['quote_valid_until'])}</div>"
            + (f"<div style='font-size:12.5px;color:#0F2A4A;margin-top:8px'>{rfq['quote_notes']}</div>" if rfq["quote_notes"] else "")
            + "</div>", unsafe_allow_html=True
        )

    if rfq["decision_outcome"]:
        outcome = rfq["decision_outcome"]
        colors = {"approved": "#1F7A5C", "rejected": "#B8453D", "changes": "#C98A2C"}
        labels = {"approved": "✓ Approved", "rejected": "✕ Rejected", "changes": "⚠ Changes requested"}
        c = colors[outcome]
        st.markdown(
            f"<div style='background:{c}0D;border:1px solid {c}33;border-radius:10px;padding:14px 16px;margin-bottom:14px'>"
            f"<div style='font-weight:700;font-size:13.5px;color:{c}'>{labels[outcome]}</div>"
            + (f"<div style='font-size:12.5px;color:#0F2A4A;margin-top:6px'>{rfq['decision_comment']}</div>" if rfq["decision_comment"] else "")
            + "</div>", unsafe_allow_html=True
        )

    st.markdown("**Assigned**")
    chips = ""
    for field in ["man_days_estimator_id", "irm_estimator_id", "presale_id"]:
        if rfq.get(field):
            chips += person_chip_html(rfq[field])
    if chips:
        st.markdown(chips, unsafe_allow_html=True)
    else:
        st.caption("No one assigned yet.")
    st.write("")

    st.markdown("**Timeline**")
    for h in reversed(rfq["history"]):
        color = STAGE_COLOR.get(h["stage"], "#5B7088")
        st.markdown(
            f"<div class='rfq-timeline-item'>"
            f"<div class='rfq-timeline-dot' style='background:{color}'></div>"
            f"<div><div class='rfq-timeline-note'>{h['note']}</div>"
            f"<div class='rfq-timeline-meta'>{h['actor']} · {time_ago(h['ts'])}</div></div>"
            f"</div>", unsafe_allow_html=True
        )
    st.markdown("---")

    # Stage-specific actions, gated by the user's currently ACTIVE role.
    # Note: being assigned to an RFQ as Man Days/IRM/Pre-Sale always lets that
    # person act on it directly (identity-based), regardless of which role
    # they've switched to, since the assignment itself is the permission.
    active_role = st.session_state.get("active_role", current_user["role"])
    is_admin = active_role == "admin"

    has_md_file = any(f["kind"] == "man_days_file" for f in rfq["files"])
    has_irm_file = any(f["kind"] == "irm_file" for f in rfq["files"])

    if not has_md_file and (is_admin or rfq.get("man_days_estimator_id") == current_user["id"]):
        render_man_days_input(rfq, current_user)
    if not has_irm_file and (is_admin or rfq.get("irm_estimator_id") == current_user["id"]):
        render_irm_input(rfq, current_user)
    if rfq["stage"] == "presale" and (is_admin or rfq.get("presale_id") == current_user["id"]):
        render_quote_form(rfq, current_user)
    if rfq["stage"] == "review" and active_role in ("admin", "management"):
        render_decision_form(rfq, current_user)
    if rfq["stage"] == "closed":
        st.caption("This RFQ is closed.")


def _report_email_results(results, fallback_label):
    """Show a small success/warning summary after a notification is triggered."""
    if not results:
        return
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    if ok:
        st.info("Notified: " + ", ".join(r["user"] for r in ok))
    if fail:
        st.warning(
            f"Could not email {fallback_label}: " + ", ".join(r["user"] for r in fail) +
            " — check Admin → Email Settings."
        )


def render_man_days_input(rfq, current_user):
    st.markdown("**Upload Man Days estimate**")
    st.caption("Uploading this file notifies Pre-Sale immediately.")
    md_file = st.file_uploader("Man Days estimate file", type=ALLOWED_DOC_EXT, key=f"md_{rfq['id']}")
    if st.button("Upload & notify Pre-Sale", key=f"md_btn_{rfq['id']}", type="primary"):
        if md_file is None:
            st.warning("Please select a file to upload.")
        else:
            results = db.submit_man_days_file(rfq["id"], md_file, current_user["full_name"])
            st.session_state[f"email_result_{rfq['id']}"] = ("Pre-Sale", results)
            st.rerun()


def render_irm_input(rfq, current_user):
    st.markdown("**Upload IRM estimate**")
    st.caption("Uploading this file notifies Pre-Sale immediately.")
    irm_file = st.file_uploader("IRM estimate file", type=ALLOWED_DOC_EXT, key=f"irm_{rfq['id']}")
    if st.button("Upload & notify Pre-Sale", key=f"irm_btn_{rfq['id']}", type="primary"):
        if irm_file is None:
            st.warning("Please select a file to upload.")
        else:
            results = db.submit_irm_file(rfq["id"], irm_file, current_user["full_name"])
            st.session_state[f"email_result_{rfq['id']}"] = ("Pre-Sale", results)
            st.rerun()


def render_quote_form(rfq, current_user):
    st.markdown("**Prepare quote for management**")
    st.caption("Uploading the quote notifies all Management users immediately.")
    amount = st.number_input("Quote amount ($)", min_value=0.0, step=500.0, key=f"amt_{rfq['id']}")
    valid_days = st.number_input("Valid for (days)", min_value=1, value=30, key=f"vd_{rfq['id']}")
    notes = st.text_area("Notes for management (optional)", key=f"qnotes_{rfq['id']}")
    quote_file = st.file_uploader("Quote / proposal file", type=ALLOWED_DOC_EXT, key=f"qfile_{rfq['id']}")
    if st.button("Send to Management", type="primary", key=f"quote_btn_{rfq['id']}"):
        if amount <= 0:
            st.warning("Enter a quote amount greater than zero.")
        elif quote_file is None:
            st.warning("Please attach the quote/proposal file before sending to Management.")
        else:
            results = db.submit_quote(rfq["id"], amount, int(valid_days), notes.strip(), quote_file, current_user["full_name"])
            st.session_state[f"email_result_{rfq['id']}"] = ("Management", results)
            st.rerun()


def render_decision_form(rfq, current_user):
    st.markdown("**Management decision**")
    comment = st.text_area("Comment (optional)", key=f"dcomment_{rfq['id']}")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("✓ Approve", type="primary", key=f"approve_{rfq['id']}", use_container_width=True):
            db.record_decision(rfq["id"], "approved", comment.strip(), current_user["full_name"])
            st.rerun()
    with c2:
        if st.button("⚠ Request changes", key=f"changes_{rfq['id']}", use_container_width=True):
            db.record_decision(rfq["id"], "changes", comment.strip(), current_user["full_name"])
            st.rerun()
    with c3:
        if st.button("✕ Reject", key=f"reject_{rfq['id']}", use_container_width=True):
            db.record_decision(rfq["id"], "rejected", comment.strip(), current_user["full_name"])
            st.rerun()


# ---------------------------------------------------------------------------
# Cards & board
# ---------------------------------------------------------------------------

def render_card(rfq):
    color = STAGE_COLOR.get(rfq["stage"], "#5B7088")
    chips = ""
    for field in ["man_days_estimator_id", "irm_estimator_id", "presale_id"]:
        if rfq.get(field):
            u = db.get_user_by_id(rfq[field])
            if u:
                role_color = ROLES.get(u["role"], {}).get("color", "#5B7088")
                chips += (f"<span style='width:22px;height:22px;border-radius:50%;background:{role_color};"
                          f"color:#fff;font-size:9.5px;font-weight:700;display:inline-flex;align-items:center;"
                          f"justify-content:center;margin-left:-7px;border:2px solid #fff' title='{u['full_name']}'>"
                          f"{initials(u['full_name'])}</span>")

    extra_line = ""
    if rfq["stage"] == "review" and rfq["quote_amount"]:
        extra_line = f"<div style='font-size:15px;font-weight:700;color:#1F7A5C;margin-bottom:6px'>${rfq['quote_amount']:,.0f}</div>"
    else:
        has_md = any(f["kind"] == "man_days_file" for f in rfq["files"])
        has_irm = any(f["kind"] == "irm_file" for f in rfq["files"])
        if has_md or has_irm:
            parts = []
            if has_md:
                parts.append("Man Days ✓")
            if has_irm:
                parts.append("IRM ✓")
            extra_line = f"<div class='rfq-card-meta' style='margin-bottom:6px'>{' · '.join(parts)}</div>"

    st.markdown(
        f"<div class='rfq-card' style='border-left:3px solid {color}'>"
        f"<div style='display:flex;justify-content:space-between'>"
        f"<span class='rfq-card-code'>{rfq['code']}</span>"
        f"<span class='rfq-dot' style='background:{PRIORITY_COLOR.get(rfq['priority'],'#5B7088')}'></span>"
        f"</div>"
        f"<div class='rfq-card-title'>{rfq['name']}</div>"
        f"<div class='rfq-card-client'>{rfq['customer']}</div>"
        f"{extra_line}"
        f"<div>{chips}</div>"
        f"<div class='rfq-card-meta' style='margin-top:6px;text-align:right'>{time_ago(rfq['created_at'])}</div>"
        f"</div>", unsafe_allow_html=True
    )
    if st.button("Open", key=f"open_{rfq['id']}", use_container_width=True):
        st.session_state.active_rfq_id = rfq["id"]
        st.rerun()


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="RFQ Pipeline — Quoting Desk", layout="wide", page_icon="📋")
    inject_css()
    db.init_db()

    if "user" not in st.session_state:
        render_login()
        return

    current_user = db.get_user_by_id(st.session_state.user["id"])  # refresh in case roles changed
    if not current_user or not current_user["active"]:
        st.error("Your account is no longer active. Contact your Admin.")
        if st.button("Sign out"):
            del st.session_state.user
            st.session_state.pop("active_role", None)
            st.rerun()
        return
    st.session_state.user = current_user

    # Keep active_role valid (e.g. an Admin may have removed a role mid-session)
    if not current_user["roles"]:
        st.error("Your account currently has no roles assigned. Contact your Admin.")
        if st.button("Sign out"):
            del st.session_state.user
            st.session_state.pop("active_role", None)
            st.rerun()
        return
    if st.session_state.get("active_role") not in current_user["roles"]:
        st.session_state.active_role = current_user["roles"][0]

    if "active_rfq_id" not in st.session_state:
        st.session_state.active_rfq_id = None
    if "show_new_rfq" not in st.session_state:
        st.session_state.show_new_rfq = False

    render_logout_bar()
    st.write("")

    col_title, col_actions = st.columns([3, 1])
    with col_title:
        st.markdown('<div class="rfq-eyebrow">QUOTING DESK</div>', unsafe_allow_html=True)
        st.markdown("## RFQ Pipeline")
    with col_actions:
        st.write("")
        can_create = st.session_state.active_role in RFQ_CREATOR_ROLES
        if can_create:
            if st.button("➕ New RFQ", type="primary", use_container_width=True):
                st.session_state.show_new_rfq = not st.session_state.show_new_rfq

    tabs_labels = ["📋 Pipeline"]
    if st.session_state.active_role == "admin":
        tabs_labels += ["👥 Users", "✉️ Email settings"]
    tabs = st.tabs(tabs_labels)

    with tabs[0]:
        if st.session_state.show_new_rfq:
            if st.session_state.active_role not in RFQ_CREATOR_ROLES:
                st.error("You don't have permission to create RFQs in your current role. Use the role switcher above if you hold another role.")
            else:
                with st.container(border=True):
                    render_new_rfq_form(current_user)
            st.write("")

        rfqs = db.fetch_rfqs()
        rfqs_by_id = {r["id"]: r for r in rfqs}

        if st.session_state.active_rfq_id and st.session_state.active_rfq_id in rfqs_by_id:
            rfq = rfqs_by_id[st.session_state.active_rfq_id]
            if st.button("← Back to pipeline"):
                st.session_state.active_rfq_id = None
                st.rerun()
            with st.container(border=True):
                render_rfq_detail(rfq, current_user)
        else:
            counts = {s["id"]: sum(1 for r in rfqs if r["stage"] == s["id"]) for s in STAGES}
            cols = st.columns(len(STAGES))
            for i, stage in enumerate(STAGES):
                with cols[i]:
                    st.markdown(f"**{stage['label']}** &nbsp;<span style='color:#8FA0B5'>{counts[stage['id']]}</span>",
                                unsafe_allow_html=True)
                    stage_rfqs = [r for r in rfqs if r["stage"] == stage["id"]]
                    if not stage_rfqs:
                        st.caption("Nothing here")
                    for rfq in stage_rfqs:
                        render_card(rfq)

    if st.session_state.active_role == "admin":
        with tabs[1]:
            render_admin_users()
        with tabs[2]:
            render_admin_email_settings()


if __name__ == "__main__":
    main()
