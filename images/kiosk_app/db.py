"""SQLite storage: users, component stock, and every issue/return with the tray photo."""
import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    card_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    roll_no     TEXT DEFAULT '',
    department  TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS components (
    name   TEXT PRIMARY KEY,           -- model class name
    label  TEXT NOT NULL,              -- what the screen shows
    stock  INTEGER NOT NULL DEFAULT 0  -- pieces currently in the lab
);
-- One row per confirmed tray scan.
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     TEXT NOT NULL REFERENCES users(card_id),
    action      TEXT NOT NULL CHECK (action IN ('issue', 'return')),
    image       TEXT,                  -- snapshot file name in data/snapshots
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);
-- The parts in that scan. detected_qty is what the model saw; qty is what the user confirmed.
CREATE TABLE IF NOT EXISTS transaction_items (
    transaction_id  INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    component       TEXT NOT NULL REFERENCES components(name),
    qty             INTEGER NOT NULL CHECK (qty > 0),
    detected_qty    INTEGER NOT NULL DEFAULT 0
);
"""

DEMO_USERS = [
    ("1001", "Demo Student", "21CS001", "Computer Engg"),
    ("1002", "Lab Assistant", "STAFF01", "Electronics"),
]


class StockError(ValueError):
    pass


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        with conn:          # commits on success, rolls back on error
            yield conn
    finally:
        conn.close()


def init():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with session() as c:
        c.executescript(SCHEMA)
        c.executemany("INSERT OR IGNORE INTO components (name, label, stock) VALUES (?, ?, ?)",
                      [(n, label, stock) for n, (label, stock) in config.COMPONENTS.items()])
        if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            c.executemany("INSERT INTO users (card_id, name, roll_no, department) VALUES (?, ?, ?, ?)", DEMO_USERS)


def rows(sql, *args):
    with session() as c:
        return [dict(r) for r in c.execute(sql, args)]


def get_user(card_id):
    found = rows("SELECT * FROM users WHERE card_id = ?", card_id)
    return found[0] if found else None


def components():
    return {r["name"]: r for r in rows("SELECT * FROM components ORDER BY label")}


def holdings(card_id=None):
    """Parts not yet returned, per user and component."""
    sql = """
        SELECT t.card_id, u.name AS user_name, i.component, c.label,
               SUM(CASE t.action WHEN 'issue' THEN i.qty ELSE -i.qty END) AS qty
        FROM transaction_items i
        JOIN transactions t ON t.id = i.transaction_id
        JOIN users u ON u.card_id = t.card_id
        JOIN components c ON c.name = i.component
        {where}
        GROUP BY t.card_id, i.component
        HAVING qty > 0
        ORDER BY u.name, c.label"""
    if card_id is None:
        return rows(sql.format(where=""))
    return rows(sql.format(where="WHERE t.card_id = ?"), card_id)


def history(card_id=None, limit=50):
    where, args = ("WHERE t.card_id = ?", (card_id,)) if card_id else ("", ())
    txs = rows(f"""SELECT t.*, u.name AS user_name FROM transactions t
                   JOIN users u ON u.card_id = t.card_id {where}
                   ORDER BY t.id DESC LIMIT ?""", *args, limit)
    for tx in txs:
        tx["items"] = rows("""SELECT i.component, c.label, i.qty, i.detected_qty
                              FROM transaction_items i JOIN components c ON c.name = i.component
                              WHERE i.transaction_id = ?""", tx["id"])
    return txs


def record(card_id, action, items, image):
    """items: {component: (qty, detected_qty)}. Updates stock in the same SQL transaction,
    so a failed check leaves nothing half-written."""
    items = {k: v for k, v in items.items() if v[0] > 0}
    if not items:
        raise StockError("Nothing to record - the tray is empty.")
    with session() as c:
        stock = {r["name"]: dict(r) for r in c.execute("SELECT * FROM components")}
        for comp in items:
            if comp not in stock:
                raise StockError(f"Unknown component: {comp}")
        if action == "issue":
            for comp, (qty, _) in items.items():
                if qty > stock[comp]["stock"]:
                    raise StockError(f"Only {stock[comp]['stock']} {stock[comp]['label']} left in stock.")
        else:
            held = {r["component"]: r["qty"] for r in c.execute("""
                SELECT i.component, SUM(CASE t.action WHEN 'issue' THEN i.qty ELSE -i.qty END) AS qty
                FROM transaction_items i JOIN transactions t ON t.id = i.transaction_id
                WHERE t.card_id = ? GROUP BY i.component""", (card_id,))}
            for comp, (qty, _) in items.items():
                if qty > held.get(comp, 0):
                    raise StockError(f"You only have {held.get(comp, 0)} {stock[comp]['label']} to return.")

        tx_id = c.execute("INSERT INTO transactions (card_id, action, image) VALUES (?, ?, ?)",
                          (card_id, action, image)).lastrowid
        sign = -1 if action == "issue" else 1
        for comp, (qty, detected) in items.items():
            c.execute("INSERT INTO transaction_items (transaction_id, component, qty, detected_qty) VALUES (?, ?, ?, ?)",
                      (tx_id, comp, qty, detected))
            c.execute("UPDATE components SET stock = stock + ? WHERE name = ?", (sign * qty, comp))
        return tx_id
