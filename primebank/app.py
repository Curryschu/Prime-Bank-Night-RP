import os, secrets, sqlite3, time
from functools import wraps
from flask import Flask, g, redirect, request, session, url_for, render_template, flash
import requests

APP_SECRET = os.environ.get("SECRET_KEY")
if not APP_SECRET:
    raise RuntimeError("SECRET_KEY fehlt. Bitte in Render als Environment Variable setzen.")

app = Flask(__name__)
app.secret_key = APP_SECRET
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
)

DATABASE = os.environ.get("DATABASE_PATH", "/var/data/primebank.sqlite")
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "")
ADMIN_IDS = {x.strip() for x in os.environ.get("ADMIN_DISCORD_IDS", "").split(",") if x.strip()}
CURRENCY = os.environ.get("CURRENCY_NAME", "Night-Dollar")

def db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DATABASE) or ".", exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def init_db():
    with app.app_context():
        conn = db()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            avatar TEXT,
            account_no TEXT UNIQUE NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT,
            receiver_id TEXT,
            amount INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        """)
        conn.commit()

@app.before_request
def ensure_db():
    init_db()

def current_user():
    uid = session.get("discord_id")
    if not uid:
        return None
    return db().execute("SELECT * FROM users WHERE discord_id=?", (uid,)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("discord_id"):
            flash("Bitte verbinde zuerst deinen Discord-Account.", "error")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapper

def is_admin():
    return session.get("discord_id") in ADMIN_IDS

@app.route("/")
def index():
    user = current_user()
    if user:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/login")
def login():
    if not all([DISCORD_CLIENT_ID, DISCORD_REDIRECT_URI]):
        flash("Discord OAuth ist noch nicht konfiguriert.", "error")
        return redirect(url_for("index"))
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "consent",
    }
    from urllib.parse import urlencode
    return redirect("https://discord.com/oauth2/authorize?" + urlencode(params))

@app.route("/callback")
def callback():
    if request.args.get("state") != session.pop("oauth_state", None):
        flash("Sicherheitsprüfung fehlgeschlagen. Bitte erneut anmelden.", "error")
        return redirect(url_for("index"))
    code = request.args.get("code")
    if not code:
        flash("Discord-Anmeldung wurde abgebrochen.", "error")
        return redirect(url_for("index"))
    token_response = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if not token_response.ok:
        flash("Discord-Anmeldung fehlgeschlagen. OAuth-Einstellungen prüfen.", "error")
        return redirect(url_for("index"))
    access_token = token_response.json().get("access_token")
    profile_response = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if not profile_response.ok:
        flash("Discord-Profil konnte nicht geladen werden.", "error")
        return redirect(url_for("index"))
    profile = profile_response.json()
    uid = str(profile["id"])
    username = profile.get("global_name") or profile.get("username") or "Discord Nutzer"
    avatar = profile.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.png?size=128" if avatar else None
    conn = db()
    existing = conn.execute("SELECT account_no FROM users WHERE discord_id=?", (uid,)).fetchone()
    account_no = existing["account_no"] if existing else "PB" + secrets.token_hex(4).upper()
    conn.execute("""
        INSERT INTO users(discord_id, username, avatar, account_no, balance)
        VALUES(?,?,?,?,0)
        ON CONFLICT(discord_id) DO UPDATE SET username=excluded.username, avatar=excluded.avatar
    """, (uid, username, avatar_url, account_no))
    conn.commit()
    session.clear()
    session["discord_id"] = uid
    session.permanent = True
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    txs = db().execute("""
        SELECT t.*, s.username AS sender_name, r.username AS receiver_name
        FROM transactions t
        LEFT JOIN users s ON s.discord_id=t.sender_id
        LEFT JOIN users r ON r.discord_id=t.receiver_id
        WHERE t.sender_id=? OR t.receiver_id=?
        ORDER BY t.created_at DESC LIMIT 12
    """, (user["discord_id"], user["discord_id"])).fetchall()
    return render_template("dashboard.html", user=user, txs=txs, currency=CURRENCY, admin=is_admin())

@app.route("/transfer", methods=["POST"])
@login_required
def transfer():
    token = session.get("csrf")
    if not token or request.form.get("csrf") != token:
        flash("Ungültige Anfrage. Bitte Seite neu laden.", "error")
        return redirect(url_for("dashboard"))
    recipient_no = request.form.get("account_no", "").strip().upper()
    try:
        amount = int(request.form.get("amount", "0"))
    except ValueError:
        amount = 0
    note = request.form.get("note", "").strip()[:120]
    if amount <= 0:
        flash("Bitte einen gültigen Betrag eingeben.", "error")
        return redirect(url_for("dashboard"))
    conn = db()
    sender = conn.execute("SELECT * FROM users WHERE discord_id=?", (session["discord_id"],)).fetchone()
    receiver = conn.execute("SELECT * FROM users WHERE account_no=?", (recipient_no,)).fetchone()
    if not receiver:
        flash("Dieses Konto wurde nicht gefunden.", "error")
    elif receiver["discord_id"] == sender["discord_id"]:
        flash("Du kannst kein Geld an dich selbst senden.", "error")
    elif sender["balance"] < amount:
        flash("Dein Kontostand reicht dafür nicht aus.", "error")
    else:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE users SET balance=balance-? WHERE discord_id=?", (amount, sender["discord_id"]))
            conn.execute("UPDATE users SET balance=balance+? WHERE discord_id=?", (amount, receiver["discord_id"]))
            conn.execute("INSERT INTO transactions(sender_id,receiver_id,amount,note,created_at) VALUES(?,?,?,?,?)",
                         (sender["discord_id"], receiver["discord_id"], amount, note, int(time.time())))
            conn.commit()
            flash(f"{amount:,} {CURRENCY} wurden an {receiver['username']} überwiesen.".replace(",", "."), "success")
        except Exception:
            conn.rollback()
            flash("Überweisung fehlgeschlagen. Bitte erneut versuchen.", "error")
    return redirect(url_for("dashboard"))

@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    if not is_admin():
        flash("Du hast keinen Zugriff auf die Verwaltung.", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            flash("Ungültige Anfrage.", "error")
            return redirect(url_for("admin"))
        account_no = request.form.get("account_no", "").strip().upper()
        try:
            amount = int(request.form.get("amount", "0"))
        except ValueError:
            amount = 0
        action = request.form.get("action")
        target = db().execute("SELECT * FROM users WHERE account_no=?", (account_no,)).fetchone()
        if not target or amount <= 0 or action not in ("add", "remove"):
            flash("Bitte Konto und positiven Betrag korrekt angeben.", "error")
        elif action == "remove" and target["balance"] < amount:
            flash("Das Konto hat nicht genügend Guthaben.", "error")
        else:
            delta = amount if action == "add" else -amount
            db().execute("UPDATE users SET balance=balance+? WHERE discord_id=?", (delta, target["discord_id"]))
            db().execute("INSERT INTO transactions(sender_id,receiver_id,amount,note,created_at) VALUES(?,?,?,?,?)",
                         (None if action == "add" else target["discord_id"],
                          target["discord_id"] if action == "add" else None,
                          amount, "Verwaltung: Gutschrift" if action == "add" else "Verwaltung: Auszahlung",
                          int(time.time())))
            db().commit()
            flash("Kontostand wurde aktualisiert.", "success")
    users = db().execute("SELECT username, account_no, balance FROM users ORDER BY username").fetchall()
    return render_template("admin.html", users=users, currency=CURRENCY)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.template_filter('timestamp')
def format_timestamp(value):
    from datetime import datetime
    return datetime.fromtimestamp(int(value)).strftime('%d.%m.%Y · %H:%M')

@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return {"csrf": session["csrf"], "logged_in": bool(session.get("discord_id"))}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
