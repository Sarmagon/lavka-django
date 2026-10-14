import random
import re
import sqlite3
import json
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler


def simulate(number):
    valid = isinstance(number, str) and re.fullmatch(r"[0-9]{1,8}", number)
    if valid and int(number) % 2 == 0 and not number.endswith("0"):
        return {"success": True}
    return {"success": False, "error": random.choice(["Банк отклонил платёж.", "Недостаточно средств.", "Счёт недоступен."])}


def handler(token, database):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/pay" or not compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 4096:
                    raise ValueError
                data = json.loads(self.rfile.read(length))
                key = data.get("key")
                if not isinstance(key, str) or not 1 <= len(key) <= 64:
                    raise ValueError
                with sqlite3.connect(database, timeout=10) as db:
                    db.execute("CREATE TABLE IF NOT EXISTS payments (key TEXT PRIMARY KEY, result TEXT NOT NULL)")
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT result FROM payments WHERE key=?", (key,)).fetchone()
                    result = row[0] if row else json.dumps(simulate(data.get("number")), ensure_ascii=False)
                    if not row:
                        db.execute("INSERT INTO payments VALUES (?, ?)", (key, result))
                encoded = result.encode()
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
                self.send_error(400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass
    return Handler
