"""
db.py — Database layer, auth, and email helper for the RFQ Pipeline app.
"""

import sqlite3
import os
import hashlib
import secrets
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "rfq_data.db")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
# admin        -> manages users, can view/decide on everything
# sales        -> can create RFQs
# man_days_est -> estimates Man Days
# irm_est      -> estimates IRM
# presale      -> prepares pricing/quote
# management   -> approves/rejects the final quote
#
# A user can hold MULTIPLE roles (e.g. Sales + Pre-Sale). Roles live in a
# separate user_roles table. When acting in the app, the user picks ONE
# active role per session (a "role switcher") — permission checks always
# use that active role. Dropdowns that assign people to an RFQ (Man Days
# Estimator / IRM Estimator / Pre-Sale) match a user if they hold that role
# among possibly several, regardless of which role is currently active.

ROLES = {
    "admin":        {"label": "Admin",               "color": "#0F2A4A"},
    "sales":        {"label": "Sales",                "color": "#1B5FA8"},
    "man_days_est": {"label": "Man Days Estimator",   "color": "#2C8C99"},
    "irm_est":      {"label": "IRM Estimator",        "color": "#3D6FA8"},
    "presale":      {"label": "Pre-Sale",             "color": "#5B7088"},
    "management":   {"label": "Management",           "color": "#1F7A5C"},
}

# Roles allowed to create a new RFQ (admin can always do everything)
RFQ_CREATOR_ROLES = {"admin", "sales"}

STAGES = [
    {"id": "received",   "label": "Received",          "color": "#5B7088"},
    {"id": "estimating", "label": "Estimating",         "color": "#2C8C99"},
    {"id": "presale",    "label": "Pre-Sale Pricing",   "color": "#3D6FA8"},
    {"id": "review",     "label": "Management Review",  "color": "#1F7A5C"},
    {"id": "closed",     "label": "Closed",             "color": "#0F2A4A"},
]
STAGE_LABEL = {s["id"]: s["label"] for s in STAGES}
STAGE_COLOR = {s["id"]: s["color"] for s in STAGES}

PRIORITY_COLOR = {"high": "#B8453D", "medium": "#C98A2C", "low": "#5B7088"}

ALLOWED_DOC_EXT = ["pdf", "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx"]

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"   # change immediately after first login


def new_id(prefix):
    return f"{prefix}_{secrets.token_hex(5)}"


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2 — no external dependency needed)
# ---------------------------------------------------------------------------

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"{salt}${digest.hex()}"


def verify_password(password, stored_hash):
    try:
        salt, _ = stored_hash.split("$")
    except ValueError:
        return False
    return hash_password(password, salt) == stored_hash


# ---------------------------------------------------------------------------
# DB connection & schema
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            full_name TEXT,
            email TEXT,
            role TEXT,
            password_hash TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            role TEXT,
            UNIQUE(user_id, role)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rfqs (
            id TEXT PRIMARY KEY,
            code TEXT,
            name TEXT,
            customer TEXT,
            priority TEXT,
            stage TEXT,
            created_by TEXT,
            created_at TEXT,
            man_days_estimator_id TEXT,
            irm_estimator_id TEXT,
            presale_id TEXT,
            quote_amount REAL,
            quote_valid_until TEXT,
            quote_notes TEXT,
            decision_outcome TEXT,
            decision_comment TEXT,
            decision_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            rfq_id TEXT,
            stage TEXT,
            actor TEXT,
            note TEXT,
            ts TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            rfq_id TEXT,
            kind TEXT,
            filename TEXT,
            stored_path TEXT,
            uploaded_by TEXT,
            uploaded_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_log (
            id TEXT PRIMARY KEY,
            rfq_id TEXT,
            to_email TEXT,
            subject TEXT,
            status TEXT,
            error TEXT,
            sent_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()

    # --- Migration: backfill user_roles from the legacy single `role` column ---
    # Covers upgrades from the previous single-role version of this app.
    # Any user who has a role set on the old column but no rows yet in
    # user_roles gets that role copied over automatically.
    legacy_users = cur.execute("SELECT id, role FROM users WHERE role IS NOT NULL AND role != ''").fetchall()
    for u in legacy_users:
        has_roles = cur.execute("SELECT COUNT(*) AS c FROM user_roles WHERE user_id=?", (u["id"],)).fetchone()["c"]
        if has_roles == 0:
            cur.execute("INSERT OR IGNORE INTO user_roles (id, user_id, role) VALUES (?,?,?)",
                        (new_id("ur"), u["id"], u["role"]))
    conn.commit()

    # Seed default admin if no users exist
    cur.execute("SELECT COUNT(*) AS c FROM users")
    if cur.fetchone()["c"] == 0:
        admin_id = new_id("u")
        cur.execute("""
            INSERT INTO users (id, username, full_name, email, role, password_hash, active, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            admin_id, DEFAULT_ADMIN_USERNAME, "Administrator", "admin@example.com",
            "admin", hash_password(DEFAULT_ADMIN_PASSWORD), 1, datetime.now().isoformat()
        ))
        cur.execute("INSERT INTO user_roles (id, user_id, role) VALUES (?,?,?)",
                    (new_id("ur"), admin_id, "admin"))
        conn.commit()

    conn.close()


# ---------------------------------------------------------------------------
# Settings (SMTP config etc.)
# ---------------------------------------------------------------------------

def get_setting(key, default=""):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Users (multi-role)
# ---------------------------------------------------------------------------

def _attach_roles(user_dict):
    """Attach a 'roles' list (all roles held) to a user dict, plus keep
    'role' as the first/primary role for places that still expect a single value."""
    if user_dict is None:
        return None
    conn = get_conn()
    rows = conn.execute("SELECT role FROM user_roles WHERE user_id=? ORDER BY rowid ASC", (user_dict["id"],)).fetchall()
    conn.close()
    roles = [r["role"] for r in rows]
    if not roles and user_dict.get("role"):
        roles = [user_dict["role"]]
    user_dict["roles"] = roles
    user_dict["role"] = roles[0] if roles else None
    return user_dict


def user_has_role(user_dict, role):
    return role in (user_dict.get("roles") or [])


def fetch_users(active_only=False):
    conn = get_conn()
    q = "SELECT * FROM users"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY full_name ASC"
    rows = [dict(r) for r in conn.execute(q)]
    conn.close()
    return [_attach_roles(u) for u in rows]


def fetch_users_by_role(role, active_only=True):
    return [u for u in fetch_users(active_only=active_only) if user_has_role(u, role)]


def get_user_by_username(username):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return _attach_roles(dict(row)) if row else None


def get_user_by_id(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return _attach_roles(dict(row)) if row else None


def set_user_roles(user_id, roles):
    """Replace the full set of roles for a user with the given list."""
    conn = get_conn()
    conn.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
    seen = set()
    for role in roles:
        if role in seen:
            continue
        seen.add(role)
        conn.execute("INSERT OR IGNORE INTO user_roles (id, user_id, role) VALUES (?,?,?)",
                     (new_id("ur"), user_id, role))
    # Keep the legacy `role` column in sync (first role) so any old code path still works.
    primary = roles[0] if roles else None
    conn.execute("UPDATE users SET role=? WHERE id=?", (primary, user_id))
    conn.commit()
    conn.close()


def create_user(username, full_name, email, roles, password):
    """roles: list of role keys, e.g. ['sales', 'presale']. Must be non-empty."""
    if isinstance(roles, str):
        roles = [roles]
    conn = get_conn()
    try:
        user_id = new_id("u")
        primary = roles[0] if roles else None
        conn.execute("""
            INSERT INTO users (id, username, full_name, email, role, password_hash, active, created_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (user_id, username.strip(), full_name.strip(), email.strip(), primary,
              hash_password(password), 1, datetime.now().isoformat()))
        for role in dict.fromkeys(roles):  # de-dupe, preserve order
            conn.execute("INSERT OR IGNORE INTO user_roles (id, user_id, role) VALUES (?,?,?)",
                         (new_id("ur"), user_id, role))
        conn.commit()
        return True, "User created."
    except sqlite3.IntegrityError:
        return False, "Username already exists."
    finally:
        conn.close()


def update_user(user_id, full_name, email, roles, active):
    if isinstance(roles, str):
        roles = [roles]
    conn = get_conn()
    primary = roles[0] if roles else None
    conn.execute("UPDATE users SET full_name=?, email=?, role=?, active=? WHERE id=?",
                 (full_name, email, primary, 1 if active else 0, user_id))
    conn.commit()
    conn.close()
    set_user_roles(user_id, roles)


def reset_password(user_id, new_password):
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
    conn.commit()
    conn.close()


def authenticate(username, password):
    user = get_user_by_username(username.strip())
    if not user:
        return None
    if not user["active"]:
        return None
    if verify_password(password, user["password_hash"]):
        return user
    return None


# ---------------------------------------------------------------------------
# RFQs
# ---------------------------------------------------------------------------

def next_code():
    conn = get_conn()
    rows = conn.execute("SELECT code FROM rfqs").fetchall()
    conn.close()
    nums = []
    for r in rows:
        try:
            nums.append(int(r["code"].split("-")[-1]))
        except Exception:
            pass
    nxt = (max(nums) + 1) if nums else 1
    return f"RFQ-2026-{nxt:03d}"


def add_history(conn, rfq_id, stage, actor, note):
    conn.execute("INSERT INTO history VALUES (?,?,?,?,?,?)",
                 (new_id("h"), rfq_id, stage, actor, note, datetime.now().isoformat()))


def create_rfq(name, customer, priority, created_by_user, man_days_est_id, irm_est_id, presale_id, files):
    """
    files: list of (kind, UploadedFile) tuples, kind in {'rfq_doc'}
    Returns the new rfq dict.
    """
    conn = get_conn()
    rfq_id = new_id("rfq")
    code = next_code()
    conn.execute("""
        INSERT INTO rfqs (id, code, name, customer, priority, stage, created_by, created_at,
                           man_days_estimator_id, irm_estimator_id, presale_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (rfq_id, code, name, customer, priority, "received", created_by_user["full_name"],
          datetime.now().isoformat(), man_days_est_id, irm_est_id, presale_id))

    assigned_names = []
    for label, uid_ in [("Man Days Estimator", man_days_est_id), ("IRM Estimator", irm_est_id), ("Pre-Sale", presale_id)]:
        if uid_:
            u = get_user_by_id(uid_)
            if u:
                assigned_names.append(f"{u['full_name']} ({label})")

    note = "RFQ logged."
    if assigned_names:
        note += " Assigned: " + ", ".join(assigned_names) + "."
    add_history(conn, rfq_id, "received", created_by_user["full_name"], note)
    conn.commit()
    conn.close()

    for uploaded_file in files:
        save_uploaded_file(rfq_id, "rfq_doc", uploaded_file, created_by_user["full_name"])

    return fetch_rfq(rfq_id)


def fetch_rfq(rfq_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if not row:
        conn.close()
        return None
    rfq = dict(row)
    rfq["history"] = [dict(h) for h in conn.execute(
        "SELECT * FROM history WHERE rfq_id=? ORDER BY ts ASC", (rfq_id,))]
    rfq["files"] = [dict(f) for f in conn.execute(
        "SELECT * FROM files WHERE rfq_id=? ORDER BY uploaded_at ASC", (rfq_id,))]
    conn.close()
    return rfq


def fetch_rfqs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM rfqs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [fetch_rfq(r["id"]) for r in rows]


def save_uploaded_file(rfq_id, kind, uploaded_file, uploaded_by):
    if uploaded_file is None:
        return
    safe_name = f"{rfq_id}_{kind}_{secrets.token_hex(3)}_{uploaded_file.name}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    conn = get_conn()
    conn.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", (
        new_id("f"), rfq_id, kind, uploaded_file.name, dest_path, uploaded_by, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def submit_man_days_file(rfq_id, uploaded_file, actor_name):
    """Estimator uploads their Man Days estimate as a file (no numeric value stored)."""
    conn = get_conn()
    _mark_estimating(conn, rfq_id)
    add_history(conn, rfq_id, "estimating", actor_name, f"Man Days estimate file uploaded: {uploaded_file.name}.")
    conn.commit()
    save_uploaded_file(rfq_id, "man_days_file", uploaded_file, actor_name)
    _advance_if_estimates_complete(rfq_id)
    conn.close()
    rfq = fetch_rfq(rfq_id)
    return notify_presale_of_estimate(rfq, "Man Days")


def submit_irm_file(rfq_id, uploaded_file, actor_name):
    """Estimator uploads their IRM estimate as a file (no numeric value stored)."""
    conn = get_conn()
    _mark_estimating(conn, rfq_id)
    add_history(conn, rfq_id, "estimating", actor_name, f"IRM estimate file uploaded: {uploaded_file.name}.")
    conn.commit()
    save_uploaded_file(rfq_id, "irm_file", uploaded_file, actor_name)
    _advance_if_estimates_complete(rfq_id)
    conn.close()
    rfq = fetch_rfq(rfq_id)
    return notify_presale_of_estimate(rfq, "IRM")


def _mark_estimating(conn, rfq_id):
    """Move a freshly-created RFQ into 'estimating' as soon as the first estimate file comes in."""
    row = conn.execute("SELECT stage FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if row["stage"] == "received":
        conn.execute("UPDATE rfqs SET stage='estimating' WHERE id=?", (rfq_id,))


def has_file_kind(rfq_id, kind):
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) AS c FROM files WHERE rfq_id=? AND kind=?", (rfq_id, kind)).fetchone()
    conn.close()
    return row["c"] > 0


def _advance_if_estimates_complete(rfq_id):
    """Once BOTH a Man Days file and an IRM file have been uploaded, move the RFQ on to Pre-Sale."""
    conn = get_conn()
    row = conn.execute("SELECT stage FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if row["stage"] != "estimating":
        conn.close()
        return
    has_md = has_file_kind(rfq_id, "man_days_file")
    has_irm = has_file_kind(rfq_id, "irm_file")
    if has_md and has_irm:
        conn.execute("UPDATE rfqs SET stage='presale' WHERE id=?", (rfq_id,))
        add_history(conn, rfq_id, "presale", "System", "Both estimate files uploaded. Sent to Pre-Sale for pricing.")
        conn.commit()
    conn.close()


def submit_quote(rfq_id, amount, valid_days, notes, quote_file, actor_name):
    from datetime import timedelta
    conn = get_conn()
    valid_until = (datetime.now() + timedelta(days=valid_days)).isoformat()
    conn.execute("UPDATE rfqs SET quote_amount=?, quote_valid_until=?, quote_notes=?, stage='review' WHERE id=?",
                 (amount, valid_until, notes, rfq_id))
    add_history(conn, rfq_id, "review", actor_name, f"Quote prepared: ${amount:,.0f}. Sent to Management for review.")
    conn.commit()
    conn.close()
    if quote_file is not None:
        save_uploaded_file(rfq_id, "quote", quote_file, actor_name)
    rfq = fetch_rfq(rfq_id)
    return notify_management_of_quote(rfq)


def record_decision(rfq_id, outcome, comment, actor_name):
    conn = get_conn()
    new_stage = "closed" if outcome in ("approved", "rejected") else "review"
    conn.execute("UPDATE rfqs SET decision_outcome=?, decision_comment=?, decision_at=?, stage=? WHERE id=?",
                 (outcome, comment, datetime.now().isoformat(), new_stage, rfq_id))
    label = {"approved": "Approved", "rejected": "Rejected", "changes": "Changes requested"}[outcome]
    note = label + (f". {comment}" if comment else ".")
    add_history(conn, rfq_id, new_stage, actor_name, note)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def is_email_configured():
    return bool(get_setting("smtp_email")) and bool(get_setting("smtp_app_password"))


def send_email(to_email, subject, body_html):
    """
    Sends an email via Gmail SMTP using an App Password stored in settings.
    Returns (success: bool, message: str).
    Configure once in the Admin > Email Settings page:
      - smtp_email: your Gmail address
      - smtp_app_password: a 16-character Gmail App Password
        (Google Account -> Security -> 2-Step Verification -> App Passwords)
    """
    sender_email = get_setting("smtp_email")
    app_password = get_setting("smtp_app_password")
    smtp_host = get_setting("smtp_host", "smtp.gmail.com")
    smtp_port = int(get_setting("smtp_port", "465"))

    if not sender_email or not app_password:
        return False, "Email is not configured yet. Go to Admin > Email Settings."

    if not to_email:
        return False, "Recipient has no email address on file."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = to_email
        msg.attach(MIMEText(body_html, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, to_email, msg.as_string())

        return True, "Sent."
    except Exception as e:
        return False, str(e)


def log_email(rfq_id, to_email, subject, status, error=""):
    conn = get_conn()
    conn.execute("INSERT INTO email_log VALUES (?,?,?,?,?,?,?)", (
        new_id("e"), rfq_id, to_email, subject, status, error, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def _send_and_log(rfq_id, to_user, subject, body):
    """Send one email, log the attempt, and return a result dict."""
    ok, msg = send_email(to_user["email"], subject, body)
    log_email(rfq_id, to_user["email"], subject, "sent" if ok else "failed", "" if ok else msg)
    return {"user": to_user["full_name"], "email": to_user["email"], "ok": ok, "message": msg}


def _rfq_info_table(rfq):
    return f"""
        <table style="border-collapse:collapse;margin:12px 0">
            <tr><td style="padding:4px 12px 4px 0;color:#5B7088">RFQ Code</td><td><strong>{rfq['code']}</strong></td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#5B7088">Name</td><td>{rfq['name']}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#5B7088">Customer</td><td>{rfq['customer']}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#5B7088">Priority</td><td>{rfq['priority'].title()}</td></tr>
        </table>
    """


def notify_assigned_resources(rfq):
    """
    Sends an email to each assigned resource (Man Days Estimator, IRM Estimator, Pre-Sale)
    when a new RFQ is created. Logs every attempt (sent or failed) to email_log so
    the admin can see what happened even if SMTP isn't configured yet.
    """
    assignees = []
    for role_label, field in [("Man Days Estimator", "man_days_estimator_id"),
                               ("IRM Estimator", "irm_estimator_id"),
                               ("Pre-Sale", "presale_id")]:
        uid_ = rfq.get(field)
        if uid_:
            u = get_user_by_id(uid_)
            if u:
                assignees.append((role_label, u))

    results = []
    for role_label, u in assignees:
        subject = f"New RFQ Assigned: {rfq['code']} — {rfq['name']}"
        body = f"""
        <div style="font-family:Arial,sans-serif;font-size:14px;color:#0F2A4A;line-height:1.6">
            <p>Hi {u['full_name']},</p>
            <p>You've been assigned as <strong>{role_label}</strong> on a new RFQ:</p>
            {_rfq_info_table(rfq)}
            <p>Please log in to the RFQ Pipeline app to review the attached documents and submit your input.</p>
            <p style="color:#8FA0B5;font-size:12px;margin-top:20px">This is an automated notification from the RFQ Pipeline app.</p>
        </div>
        """
        r = _send_and_log(rfq["id"], u, subject, body)
        r["role"] = role_label
        results.append(r)

    return results


def notify_presale_of_estimate(rfq, estimate_kind):
    """
    Sends an email to the assigned Pre-Sale person(s) whenever a Man Days or IRM
    estimate file is uploaded. estimate_kind is 'Man Days' or 'IRM'.
    Fires once per upload (so Pre-Sale may receive two separate emails).
    """
    presale_id = rfq.get("presale_id")
    if not presale_id:
        return []
    u = get_user_by_id(presale_id)
    if not u:
        return []

    subject = f"{estimate_kind} Estimate Uploaded: {rfq['code']} — {rfq['name']}"
    body = f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;color:#0F2A4A;line-height:1.6">
        <p>Hi {u['full_name']},</p>
        <p>The <strong>{estimate_kind}</strong> estimate file has just been uploaded for this RFQ:</p>
        {_rfq_info_table(rfq)}
        <p>Log in to the RFQ Pipeline app to review the attached file. Once both Man Days and IRM
           files are in, this RFQ will move to your Pre-Sale queue for pricing.</p>
        <p style="color:#8FA0B5;font-size:12px;margin-top:20px">This is an automated notification from the RFQ Pipeline app.</p>
    </div>
    """
    return [_send_and_log(rfq["id"], u, subject, body)]


def notify_management_of_quote(rfq):
    """
    Sends an email to all active Management users whenever Pre-Sale uploads a quote.
    """
    mgmt_users = fetch_users_by_role("management")
    results = []
    for u in mgmt_users:
        subject = f"Quote Ready for Review: {rfq['code']} — {rfq['name']}"
        amount_str = f"${rfq['quote_amount']:,.0f}" if rfq.get("quote_amount") else "—"
        body = f"""
        <div style="font-family:Arial,sans-serif;font-size:14px;color:#0F2A4A;line-height:1.6">
            <p>Hi {u['full_name']},</p>
            <p>Pre-Sale has submitted a quote for this RFQ, ready for your review:</p>
            {_rfq_info_table(rfq)}
            <table style="border-collapse:collapse;margin:12px 0">
                <tr><td style="padding:4px 12px 4px 0;color:#5B7088">Quoted amount</td><td><strong>{amount_str}</strong></td></tr>
            </table>
            <p>Log in to the RFQ Pipeline app to approve, reject, or request changes.</p>
            <p style="color:#8FA0B5;font-size:12px;margin-top:20px">This is an automated notification from the RFQ Pipeline app.</p>
        </div>
        """
        results.append(_send_and_log(rfq["id"], u, subject, body))

    return results
