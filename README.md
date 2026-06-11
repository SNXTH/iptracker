# IP Tracker

A self-hosted link tracker. Paste your tracking link anywhere — every click logs the visitor's IP, location, browser, OS, and device to a local SQLite database. View everything in a live dashboard.

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the server

```bash
python app.py
```

Open http://127.0.0.1:5000 in your browser.

---

## How it works

1. Paste a destination URL into the dashboard → get a tracking link like `http://yourdomain.com/t/abc12345`
2. Share that link anywhere (email, social, wherever)
3. When someone clicks it, the server captures:
   - IP address
   - Country, city, region, ISP (via ip-api.com — free, no key needed)
   - Browser name + version
   - Operating system
   - Device type (Desktop / Mobile / Tablet)
   - Referer (where they came from)
   - Timestamp
4. They get redirected to your destination URL — seamlessly
5. You see all clicks live in the dashboard

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/create` | Create a tracking link. Body: `{"destination": "https://..."}` |
| GET | `/api/links` | List all links with click counts |
| GET | `/api/clicks/:track_id` | All raw clicks for a link |
| GET | `/api/stats/:track_id` | Aggregated stats (countries, devices) |
| DELETE | `/api/delete/:track_id` | Delete a link and all its clicks |
| GET | `/t/:track_id` | The tracking redirect URL (share this one) |

---

## Deployment (make it public)

To use this on real traffic you need a public URL. Easiest options:

**Option A — ngrok (instant, for testing)**
```bash
pip install flask
python app.py &
ngrok http 5000
```
ngrok gives you a public URL like `https://abc123.ngrok.io`.

**Option B — VPS (DigitalOcean, Linode, etc.)**
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```
Point a domain at your server IP. Use nginx as a reverse proxy.

**Option C — Railway / Render (free tier)**
Push to GitHub, connect the repo. Set start command to:
```
gunicorn app:app
```

---

## Notes

- ip-api.com allows 45 requests/minute on the free tier. For high traffic, consider a paid plan or self-hosted geolocation (MaxMind GeoLite2).
- The SQLite database (`tracker.db`) is created automatically on first run.
- Private/local IPs (127.0.0.1, 192.168.x.x) are detected and labeled "Local" instead of geolocated.
