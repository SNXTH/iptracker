from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast
from urllib.parse import urlparse

from flask import Flask, g, jsonify, redirect, render_template, request
import requests
import random
import sqlite3
import string
from user_agents import parse as ua_parse  # type: ignore[import]

app = Flask(__name__)
DB = Path(__file__).resolve().parent / "tracker.db"


def get_db():
    conn = getattr(g, "_database", None)
    if conn is None:
        conn = sqlite3.connect(DB, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        g._database = conn
    return conn


@app.teardown_appcontext
def close_db(exception: Optional[BaseException] = None) -> None:
    conn = getattr(g, "_database", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT UNIQUE NOT NULL,
            destination TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT NOT NULL,
            ip TEXT,
            country TEXT,
            city TEXT,
            region TEXT,
            isp TEXT,
            browser TEXT,
            browser_version TEXT,
            os TEXT,
            device TEXT,
            referer TEXT,
            clicked_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def generate_id(length: int = 10) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


def geolocate(ip: str) -> Dict[str, str]:
    """Use ip-api.com free tier (no key needed, 45 req/min limit)."""
    try:
        # Skip loopback/private IPs
        if ip in ("127.0.0.1", "::1") or ip.startswith("192.168.") or ip.startswith("10."):
            return {"country": "Local", "city": "Local", "region": "", "isp": ""}
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=country,city,regionName,isp,status", timeout=3)
        data = r.json()
        if data.get("status") == "success":
            return {
                "country": data.get("country", ""),
                "city": data.get("city", ""),
                "region": data.get("regionName", ""),
                "isp": data.get("isp", ""),
            }
    except Exception:
        pass
    return {"country": "Unknown", "city": "Unknown", "region": "", "isp": ""}


def parse_ua(ua_string: str) -> Tuple[str, str, str, str]:
    try:
        ua = ua_parse(ua_string or "")
        browser = getattr(ua.browser, "family", "Unknown") or "Unknown"
        version = getattr(ua.browser, "version_string", "") or ""
        os_name = f"{getattr(ua.os, 'family', 'Unknown')} {getattr(ua.os, 'version_string', '')}".strip() or "Unknown"
        if getattr(ua, "is_mobile", False):
            device = "Mobile"
        elif getattr(ua, "is_tablet", False):
            device = "Tablet"
        else:
            device = "Desktop"
        return browser, version, os_name, device
    except Exception:
        return "Unknown", "", "Unknown", "Unknown"


# ── Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/create", methods=["POST"])
def create_link() -> Any:
    raw_data: Any = request.get_json(silent=True)
    if not isinstance(raw_data, dict):
        return jsonify({"error": "JSON body required"}), 400

    data = cast(dict[str, Any], raw_data)
    destination_raw = data.get("destination", "")
    destination = str(destination_raw).strip()
    if not destination:
        return jsonify({"error": "destination is required"}), 400

    if not destination.startswith(("http://", "https://")):
        destination = "https://" + destination

    parsed = urlparse(destination)
    if not parsed.scheme or not parsed.netloc:
        return jsonify({"error": "destination must be a valid URL"}), 400

    conn = get_db()
    created_at = datetime.now(timezone.utc).isoformat()
    track_id = None
    while track_id is None:
        candidate = generate_id()
        try:
            conn.execute(
                "INSERT INTO links (track_id, destination, created_at) VALUES (?, ?, ?)",
                (candidate, destination, created_at),
            )
            conn.commit()
            track_id = candidate
        except sqlite3.IntegrityError:
            continue

    tracking_url = request.host_url.rstrip("/") + "/t/" + track_id
    return jsonify({"track_id": track_id, "tracking_url": tracking_url, "destination": destination})


@app.route("/t/<track_id>")
def track(track_id: str) -> Any:
    conn = get_db()
    row = conn.execute("SELECT destination FROM links WHERE track_id = ?", (track_id,)).fetchone()
    if not row:
        conn.close()
        return "Link not found", 404

    destination = row["destination"]

    # Collect visitor data
    ip = request.headers.get("X-Forwarded-For", request.remote_addr) or ""
    ip = ip.split(",")[0].strip()

    ua_string = request.headers.get("User-Agent", "")
    referer = request.headers.get("Referer", "")
    browser, version, os_name, device = parse_ua(ua_string)
    geo = geolocate(ip)
    clicked_at = datetime.now(timezone.utc).isoformat()

    conn.execute("""
        INSERT INTO clicks
        (track_id, ip, country, city, region, isp, browser, browser_version, os, device, referer, clicked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        track_id, ip,
        geo["country"], geo["city"], geo["region"], geo["isp"],
        browser, version, os_name, device,
        referer, clicked_at
    ))
    conn.commit()

    return redirect(destination)


@app.route("/api/links")
def list_links() -> Any:
    conn = get_db()
    rows = conn.execute("""
        SELECT l.track_id, l.destination, l.created_at,
               COUNT(c.id) as click_count
        FROM links l
        LEFT JOIN clicks c ON l.track_id = c.track_id
        GROUP BY l.track_id
        ORDER BY l.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/clicks/<track_id>")
def get_clicks(track_id: str) -> Any:
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM clicks WHERE track_id = ? ORDER BY clicked_at DESC
    """, (track_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats/<track_id>")
def get_stats(track_id: str) -> Any:
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM clicks WHERE track_id = ?", (track_id,)).fetchone()[0]
    unique = conn.execute("SELECT COUNT(DISTINCT ip) FROM clicks WHERE track_id = ?", (track_id,)).fetchone()[0]
    countries = conn.execute("SELECT COUNT(DISTINCT country) FROM clicks WHERE track_id = ?", (track_id,)).fetchone()[0]
    by_country = conn.execute("""
        SELECT country, COUNT(*) as cnt FROM clicks
        WHERE track_id = ? GROUP BY country ORDER BY cnt DESC LIMIT 10
    """, (track_id,)).fetchall()
    by_device = conn.execute("""
        SELECT device, COUNT(*) as cnt FROM clicks
        WHERE track_id = ? GROUP BY device
    """, (track_id,)).fetchall()
    conn.close()
    return jsonify({
        "total": total,
        "unique_ips": unique,
        "countries": countries,
        "by_country": [dict(r) for r in by_country],
        "by_device": [dict(r) for r in by_device],
    })


@app.route("/api/delete/<track_id>", methods=["DELETE"])
def delete_link(track_id: str) -> Any:
    conn = get_db()
    conn.execute("DELETE FROM clicks WHERE track_id = ?", (track_id,))
    conn.execute("DELETE FROM links WHERE track_id = ?", (track_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    print("✓ Database initialised")
    print("✓ Server running at http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
