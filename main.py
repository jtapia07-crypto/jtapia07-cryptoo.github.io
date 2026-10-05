"""BioRifa API v2 — uvicorn main:app --host 0.0.0.0 --port 8000"""
import csv, hashlib, io, logging, os, re, secrets, sqlite3, time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Literal
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, EmailStr, Field, field_validator
import qrcode
from notify import send_email, send_instagram, send_whatsapp

logging.basicConfig(level=logging.INFO)
DB = os.getenv("DB_PATH", "rifa.db")
TOTAL = int(os.getenv("TOTAL_NUMBERS", 100))
ADMIN = os.getenv("ADMIN_TOKEN", "")
API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000")
HOLD_DEFAULT, HOLD_TRANSFER = 15 * 60, int(os.getenv("HOLD_TRANSFER_H", 24)) * 3600
MAX_PER_ORDER, MAX_PENDING_PER_EMAIL = 10, 2
PRICES = ((5, 8000), (3, 5000), (1, 2000))  # (cantidad, precio del pack)
if len(ADMIN) < 16:
    raise RuntimeError("ADMIN_TOKEN obligatorio (mínimo 16 caracteres)")

app = FastAPI(title="BioRifa", docs_url=None if os.getenv("ENV") == "prod" else "/docs", redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Admin-Token"])

# ---------- base de datos ----------
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=10, isolation_level=None)  # autocommit; las transacciones son explícitas
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA busy_timeout=10000")
    return c

@contextmanager
def tx():
    """BEGIN IMMEDIATE toma el lock de escritura: las comprobaciones dentro de la transacción no tienen carreras."""
    c = conn()
    try:
        c.execute("BEGIN IMMEDIATE"); yield c; c.execute("COMMIT")
    except BaseException:
        try: c.execute("ROLLBACK")
        except sqlite3.Error: pass
        raise
    finally:
        c.close()

_c = conn()  # executescript hace COMMIT implícito: se usa fuera de tx()
_c.executescript("""
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, rut TEXT NOT NULL,
        email TEXT NOT NULL, phone TEXT NOT NULL, instagram TEXT NOT NULL DEFAULT '', method TEXT NOT NULL,
        amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN('pending','paid')),
        created REAL NOT NULL, paid REAL);
    CREATE TABLE IF NOT EXISTS numbers(num INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS draws(id INTEGER PRIMARY KEY, num INTEGER UNIQUE NOT NULL, order_id INTEGER NOT NULL,
        pool_hash TEXT NOT NULL, pool_size INTEGER NOT NULL, at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status, created);
    CREATE INDEX IF NOT EXISTS ix_orders_email ON orders(email, status);
    CREATE INDEX IF NOT EXISTS ix_numbers_order ON numbers(order_id);""")
_c.close()

# Una orden pendiente está "viva" mientras no venza su reserva (15 min en línea, HOLD_TRANSFER_H en transferencia).
ALIVE = "(o.status='paid' OR o.created + CASE o.method WHEN 'transferencia' THEN :th ELSE :hd END >= :now)"
def alive_args() -> dict: return {"th": HOLD_TRANSFER, "hd": HOLD_DEFAULT, "now": time.time()}

# ---------- utilidades ----------
def price(n: int) -> int:
    """Precio SIEMPRE calculado en el servidor. 5→$8.000, 3→$5.000, 1→$2.000 (voraz)."""
    t = 0
    for size, p in PRICES: t += (n // size) * p; n %= size
    return t

_hits: dict[str, deque] = defaultdict(deque)
def limit(r: Request, key: str, n: int, secs: int) -> None:
    ip = (r.headers.get("x-forwarded-for", "").split(",")[0].strip() if os.getenv("TRUST_PROXY") == "1"
          else (r.client.host if r.client else "")) or "?"
    q, now = _hits[f"{key}:{ip}"], time.time()
    while q and q[0] < now - secs: q.popleft()
    if len(q) >= n: raise HTTPException(429, "Demasiadas solicitudes, espera un momento")
    q.append(now)

def admin(r: Request, tok: str | None) -> None:
    limit(r, "adm", 60, 60)
    if not tok or not secrets.compare_digest(tok.encode(), ADMIN.encode()): raise HTTPException(401, "No autorizado")

def mask(name: str) -> str:  # nombres públicos: "Camila Rojas" → "Camila R."
    p = name.split(); return p[0] + (f" {p[-1][0]}." if len(p) > 1 else "")

def cell(v) -> str:  # evita inyección de fórmulas en Excel
    s = "" if v is None else str(v); return "'" + s if s[:1] in "=+-@\t\r" else s

def rut_fmt(v: str) -> str | None:
    r = re.sub(r"[.\-\s]", "", v).upper()
    if not re.fullmatch(r"\d{7,8}[\dK]", r): return None
    s, m = 0, 2
    for d in reversed(r[:-1]): s += int(d) * m; m = 2 if m == 7 else m + 1
    x = 11 - s % 11
    return f"{r[:-1]}-{r[-1]}" if r[-1] == ("0" if x == 11 else "K" if x == 10 else str(x)) else None

class OrderIn(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    rut: str
    email: EmailStr
    phone: str
    instagram: str = ""
    method: Literal["transferencia"] = "transferencia"  # agregar "webpay" cuando exista la integración real
    numbers: list[int] = Field(min_length=1, max_length=MAX_PER_ORDER)

    @field_validator("name")
    @classmethod
    def _name(cls, v): return " ".join(v.split())
    @field_validator("rut")
    @classmethod
    def _rut(cls, v):
        r = rut_fmt(v)
        if not r: raise ValueError("RUT inválido")
        return r
    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        d = re.sub(r"\D", "", v)
        if len(d) == 9 and d[0] == "9": d = "56" + d
        if not 11 <= len(d) <= 15: raise ValueError("Teléfono inválido")
        return "+" + d
    @field_validator("instagram")
    @classmethod
    def _ig(cls, v):
        v = v.strip().lstrip("@")
        if v and not re.fullmatch(r"[A-Za-z0-9._]{1,30}", v): raise ValueError("Instagram inválido")
        return "@" + v if v else ""
    @field_validator("numbers")
    @classmethod
    def _nums(cls, v):
        if len(set(v)) != len(v) or any(not 1 <= n <= TOTAL for n in v): raise ValueError("Números inválidos")
        return sorted(v)

# ---------- API pública ----------
@app.get("/api/health")
def health(): return {"ok": True}

@app.get("/api/stats")
def stats():
    c = conn()
    try:
        row = c.execute(f"""SELECT COALESCE(SUM(o.status='paid'),0) paid_n, COUNT(*) held_n FROM numbers n
                            JOIN orders o ON o.id=n.order_id WHERE {ALIVE}""", alive_args()).fetchone()
        raised = c.execute("SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='paid'").fetchone()[0]
        return {"total": TOTAL, "sold": row["paid_n"], "reserved": row["held_n"] - row["paid_n"], "raised": raised}
    finally: c.close()

@app.get("/api/numbers")
def numbers():
    c = conn()
    try:
        rows = c.execute(f"SELECT n.num, o.status FROM numbers n JOIN orders o ON o.id=n.order_id WHERE {ALIVE}", alive_args()).fetchall()
        return {"total": TOTAL, "sold": sorted(r["num"] for r in rows if r["status"] == "paid"),
                "reserved": sorted(r["num"] for r in rows if r["status"] != "paid")}
    finally: c.close()

@app.post("/api/orders")
def create_order(o: OrderIn, request: Request):
    limit(request, "ord", 10, 60)
    now = time.time()
    with tx() as c:
        c.execute("""DELETE FROM orders WHERE status='pending'
                     AND created + CASE method WHEN 'transferencia' THEN ? ELSE ? END < ?""", (HOLD_TRANSFER, HOLD_DEFAULT, now))
        if c.execute("SELECT COUNT(*) FROM orders WHERE email=? AND status='pending'", (o.email,)).fetchone()[0] >= MAX_PENDING_PER_EMAIL:
            raise HTTPException(429, "Ya tienes reservas pendientes de pago con este correo")
        taken = [n for n in o.numbers if c.execute("SELECT 1 FROM numbers WHERE num=?", (n,)).fetchone()]
        if taken: raise HTTPException(409, {"message": f"Número(s) ya tomado(s): {', '.join(map(str, taken))}", "taken": taken})
        amount = price(len(o.numbers))
        oid = c.execute("INSERT INTO orders(name,rut,email,phone,instagram,method,amount,created) VALUES(?,?,?,?,?,?,?,?)",
                        (o.name, o.rut, o.email, o.phone, o.instagram, o.method, amount, now)).lastrowid
        c.executemany("INSERT INTO numbers(num,order_id) VALUES(?,?)", [(n, oid) for n in o.numbers])
    hold = HOLD_TRANSFER if o.method == "transferencia" else HOLD_DEFAULT
    return {"order_id": oid, "amount": amount, "hold_minutes": hold // 60, "numbers": o.numbers}

@app.get("/api/tickets/{code}")  # el QR del comprobante apunta aquí: cualquiera puede verificarlo, sin datos personales
def ticket(code: str, request: Request):
    limit(request, "tk", 30, 60)
    c = conn()
    try:
        o = c.execute("SELECT id,name FROM orders WHERE code=? AND status='paid'", (code,)).fetchone()
        if not o: return {"valid": False}
        return {"valid": True, "holder": mask(o["name"]),
                "numbers": [r[0] for r in c.execute("SELECT num FROM numbers WHERE order_id=? ORDER BY num", (o["id"],))]}
    finally: c.close()

@app.get("/api/draw/latest")
def latest():
    c = conn()
    try:
        r = c.execute("SELECT d.num, o.name, d.pool_hash, d.pool_size, d.at FROM draws d JOIN orders o ON o.id=d.order_id ORDER BY d.id DESC LIMIT 1").fetchone()
        return {**{k: r[k] for k in ("num", "pool_hash", "pool_size", "at")}, "name": mask(r["name"])} if r else None
    finally: c.close()

# ---------- administración ----------
@app.get("/api/admin/orders")
def admin_orders(request: Request, x_admin_token: str | None = Header(None)):
    admin(request, x_admin_token)
    c = conn()
    try:
        rows = c.execute("""SELECT o.*, group_concat(n.num) nums FROM orders o LEFT JOIN numbers n ON n.order_id=o.id
                            GROUP BY o.id ORDER BY o.id DESC""").fetchall()
        return [{**dict(r), "numbers": sorted(int(x) for x in r["nums"].split(","))} if r["nums"] else {**dict(r), "numbers": []} for r in rows]
    finally: c.close()

@app.get("/api/admin/export.csv")
def export(request: Request, x_admin_token: str | None = Header(None)):
    rows = admin_orders(request, x_admin_token); s = io.StringIO(); w = csv.writer(s)
    w.writerow(["codigo", "nombre", "rut", "correo", "telefono", "instagram", "numeros", "monto", "estado"])
    for r in rows:
        w.writerow([r["code"], cell(r["name"]), r["rut"], r["email"], r["phone"], r["instagram"],
                    " ".join(map(str, r["numbers"])), r["amount"], r["status"]])  # solo el nombre es texto libre
    return Response("\ufeff" + s.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=rifa.csv"})

@app.post("/api/admin/orders/{oid}/confirm")
def confirm(oid: int, bg: BackgroundTasks, request: Request, x_admin_token: str | None = Header(None)):
    """Idempotente: confirmar dos veces no reenvía comprobantes. Punto de conexión para el callback de una pasarela."""
    admin(request, x_admin_token)
    with tx() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o: raise HTTPException(404, "Orden inexistente o reserva expirada")
        nums = [r[0] for r in c.execute("SELECT num FROM numbers WHERE order_id=? ORDER BY num", (oid,))]
        if o["status"] == "paid": return {"code": o["code"], "numbers": nums, "already": True}
        code = "BR-" + secrets.token_hex(4).upper()
        c.execute("UPDATE orders SET status='paid', code=?, paid=? WHERE id=?", (code, time.time(), oid))
    buf = io.BytesIO(); qrcode.make(f"{API_URL}/api/tickets/{code}").save(buf, "PNG")
    msg = f"¡Gracias {o['name']}! Pago confirmado. Comprobante {code}. Tus números: {', '.join(map(str, nums))}."
    bg.add_task(send_email, o["email"], f"Comprobante {code} · BioRifa", msg, buf.getvalue())
    bg.add_task(send_whatsapp, o["phone"], msg)
    return {"code": code, "numbers": nums, "already": False}

@app.post("/api/admin/draw")
def draw(bg: BackgroundTasks, request: Request, x_admin_token: str | None = Header(None)):
    """El hash del universo sorteado queda guardado: permite auditar a posteriori que nadie fue excluido."""
    admin(request, x_admin_token)
    with tx() as c:
        pool = c.execute("""SELECT n.num, o.id oid, o.name, o.email, o.phone, o.instagram FROM numbers n
                            JOIN orders o ON o.id=n.order_id WHERE o.status='paid'
                            AND n.num NOT IN (SELECT num FROM draws) ORDER BY n.num""").fetchall()
        if not pool: raise HTTPException(400, "No hay números elegibles")
        h = hashlib.sha256(",".join(str(r["num"]) for r in pool).encode()).hexdigest()
        w = secrets.choice(pool)
        c.execute("INSERT INTO draws(num,order_id,pool_hash,pool_size,at) VALUES(?,?,?,?,?)", (w["num"], w["oid"], h, len(pool), time.time()))
    msg = f"🎉 ¡Felicitaciones {w['name']}! Tu número {w['num']} ganó la BioRifa. Responde este mensaje para coordinar la entrega."
    bg.add_task(send_email, w["email"], "¡Ganaste la BioRifa! 🧬", msg)
    bg.add_task(send_whatsapp, w["phone"], msg)
    bg.add_task(send_instagram, w["instagram"], msg)
    return {"num": w["num"], "name": mask(w["name"]), "pool_size": len(pool), "pool_hash": h}
