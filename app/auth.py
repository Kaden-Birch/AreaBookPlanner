"""Local accounts and server-owned sessions; administrators have full application access."""
import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from .database import get_db

router = APIRouter(prefix="/api/auth", tags=["accounts"])
admin_router = APIRouter(prefix="/api/admin", tags=["administration"])
ROLES = ("sales", "client_success", "it", "manager", "admin")
COOKIE = "areabook_session"
SESSION_SECONDS = 8 * 60 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_ai_settings (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 api_key TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
 is_active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS areas (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 latitude REAL NOT NULL, longitude REAL NOT NULL, default_zoom INTEGER NOT NULL DEFAULT 12,
 is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS user_roles (
 user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL,
 PRIMARY KEY(user_id, role)
);
CREATE TABLE IF NOT EXISTS user_role_areas (
 user_id INTEGER NOT NULL, role TEXT NOT NULL, area_id INTEGER NOT NULL REFERENCES areas(id),
 is_default INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id, role, area_id),
 FOREIGN KEY(user_id, role) REFERENCES user_roles(user_id, role) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS auth_sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 active_role TEXT, area_id INTEGER REFERENCES areas(id), expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
 key TEXT PRIMARY KEY, failures INTEGER NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS account_audit (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
 target_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password, encoded):
    try:
        _, salt, expected = encoded.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

    @field_validator('username')
    @classmethod
    def clean_username(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('Username is required')
        return value


def require_password(password):
    if len(password) < 12:
        raise HTTPException(422, "Use a password of at least 12 characters")


def session_user(request, conn):
    token = request.cookies.get(COOKIE, "")
    row = conn.execute("""SELECT u.*, s.active_role, s.area_id, s.token_hash FROM auth_sessions s
        JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1""",
        (token_hash(token), time.time())).fetchone()
    if row is None:
        raise HTTPException(401, "Please sign in")
    user = dict(row)
    user["roles"] = [r[0] for r in conn.execute("SELECT role FROM user_roles WHERE user_id=?", (user["id"],))]
    if 'admin' in user['roles']:
        user['roles'] = list(ROLES)
    if user["active_role"] and user["active_role"] not in user["roles"]:
        raise HTTPException(401, "Your access changed. Please sign in again")
    return user


def public_user(conn, user):
    result = {k: user[k] for k in ("id", "username", "display_name", "must_change_password", "active_role", "area_id", "roles")}
    result["areas"] = [dict(r) for r in conn.execute("""SELECT a.*, ua.role, ua.is_default
        FROM user_role_areas ua JOIN areas a ON a.id=ua.area_id
        WHERE ua.user_id=? AND a.is_active=1 ORDER BY a.name""", (user["id"],))]
    if 'admin' in user['roles']:
        result['areas'] = [dict(a) | {'role': role, 'is_default': 0}
                           for a in conn.execute('SELECT * FROM areas WHERE is_active=1 ORDER BY name')
                           for role in ROLES if role != 'admin']
    return result


def new_session(conn, user_id, response, request):
    conn.execute('DELETE FROM auth_sessions WHERE expires_at<=? OR token_hash=?',
                 (time.time(), token_hash(request.cookies.get(COOKIE, ''))))
    role = conn.execute("SELECT role FROM user_roles WHERE user_id=? ORDER BY role='admin', role LIMIT 1", (user_id,)).fetchone()[0]
    area = conn.execute("""SELECT ua.area_id FROM user_role_areas ua JOIN areas a ON a.id=ua.area_id
        WHERE ua.user_id=? AND ua.role=? AND a.is_active=1 ORDER BY ua.is_default DESC, a.name LIMIT 1""", (user_id, role)).fetchone()
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,?)", (token_hash(token), user_id, role, area[0] if area else None, time.time()+SESSION_SECONDS))
    # HTTPS is required for LAN deployments; localhost HTTP remains usable for development.
    secure = request.url.scheme == "https" or request.url.hostname not in ("localhost", "127.0.0.1", "testserver")
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=secure, samesite="strict", path="/")


@router.get("/status")
def status():
    with get_db() as conn:
        return {"setup_required": conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None}


@router.post("/setup")
def setup(data: Credentials, request: Request, response: Response):
    require_password(data.password)
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(409, "Administrator setup is already complete")
        uid = conn.execute("INSERT INTO users(username,display_name,password_hash) VALUES (?,?,?)",
                           (data.username.strip(), data.username.strip(), password_hash(data.password))).lastrowid
        conn.execute("INSERT INTO user_roles VALUES (?, 'admin')", (uid,))
        new_session(conn, uid, response, request)
    return {"ok": True}


@router.post("/login")
def login(data: Credentials, request: Request, response: Response):
    key = token_hash((request.client.host if request.client else "unknown") + ":" + data.username.strip().lower())
    failed = False
    with get_db() as conn:
        limit = conn.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
        if limit and limit["expires_at"] > time.time() and limit["failures"] >= 10:
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes")
        user = conn.execute("SELECT * FROM users WHERE username=?", (data.username.strip(),)).fetchone()
        valid = check_password(data.password, user["password_hash"] if user else password_hash("dummy-password"))
        if not user or not valid or not user["is_active"]:
            failures = limit["failures"] + 1 if limit and limit["expires_at"] > time.time() else 1
            conn.execute("INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)", (key, failures, time.time()+900))
            failed = True
        else:
            conn.execute("DELETE FROM login_attempts WHERE key=?", (key,))
            new_session(conn, user["id"], response, request)
    if failed:
        raise HTTPException(401, "Incorrect username or password")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    with get_db() as conn:
        return public_user(conn, session_user(request, conn))


class PersonalAISettings(BaseModel):
    api_key: str | None = Field(default=None, max_length=4096)
    model: str = Field(default='', max_length=150)


@router.get('/preferences')
def preferences(request: Request):
    with get_db() as conn:
        user = session_user(request, conn)
        if user['must_change_password']: raise HTTPException(403, 'Change your password first')
        row = conn.execute('SELECT api_key,model FROM user_ai_settings WHERE user_id=?', (user['id'],)).fetchone()
        return {'ai_configured': bool(row and row['api_key']), 'model': row['model'] if row else ''}


@router.put('/preferences')
def save_preferences(payload: PersonalAISettings, request: Request):
    with get_db() as conn:
        user = session_user(request, conn)
        if user['must_change_password']: raise HTTPException(403, 'Change your password first')
        conn.execute('INSERT OR IGNORE INTO user_ai_settings(user_id) VALUES (?)', (user['id'],))
        conn.execute('UPDATE user_ai_settings SET model=? WHERE user_id=?', (payload.model.strip(), user['id']))
        if payload.api_key is not None:
            conn.execute('UPDATE user_ai_settings SET api_key=? WHERE user_id=?', (payload.api_key.strip(), user['id']))
    return preferences(request)


@router.post("/logout")
def logout(request: Request, response: Response):
    with get_db() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash(request.cookies.get(COOKIE, "")),))
    response.delete_cookie(COOKIE)
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    password: str = Field(min_length=12, max_length=256)


@router.post("/password")
def change_password(data: PasswordChange, request: Request, response: Response):
    with get_db() as conn:
        user = session_user(request, conn)
        if not check_password(data.current_password, user["password_hash"]):
            raise HTTPException(403, "Current password is incorrect")
        conn.execute("UPDATE users SET password_hash=?, must_change_password=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (password_hash(data.password), user["id"]))
        conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (user["id"],))
        new_session(conn, user["id"], response, request)
    return {"ok": True}


class Workspace(BaseModel):
    role: str
    area_id: int | None = None


@router.post("/workspace")
def workspace(data: Workspace, request: Request):
    with get_db() as conn:
        user = session_user(request, conn)
        if user["must_change_password"]:
            raise HTTPException(403, "Change your password first")
        if data.role not in user["roles"]:
            raise HTTPException(403, "Role is not assigned")
        areas = conn.execute("""SELECT ua.area_id FROM user_role_areas ua JOIN areas a ON a.id=ua.area_id
            WHERE user_id=? AND role=? AND a.is_active=1 ORDER BY is_default DESC, a.name""", (user["id"], data.role)).fetchall()
        if 'admin' in user['roles']:
            areas = conn.execute('SELECT id FROM areas WHERE is_active=1 ORDER BY name').fetchall()
        area_id = data.area_id if data.area_id is not None else (areas[0][0] if areas else None)
        if area_id is not None and area_id not in [r[0] for r in areas]:
            raise HTTPException(403, "Area is not assigned to this role")
        conn.execute("UPDATE auth_sessions SET active_role=?,area_id=? WHERE token_hash=?", (data.role, area_id, user["token_hash"]))
    return {"ok": True}


def require_admin(request, conn):
    user = session_user(request, conn)
    if "admin" not in user["roles"] or user["must_change_password"]:
        raise HTTPException(403, "Administrator access required")
    return user


class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    default_zoom: int = Field(default=12, ge=1, le=19)
    is_active: bool = True

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError('Area name is required')
        return value.strip()


@admin_router.get("/areas")
def areas(request: Request):
    with get_db() as conn:
        require_admin(request, conn)
        return [dict(r) for r in conn.execute("SELECT * FROM areas ORDER BY name")]


@admin_router.post("/areas")
def create_area(data: AreaIn, request: Request):
    with get_db() as conn:
        require_admin(request, conn)
        if conn.execute('SELECT 1 FROM areas WHERE name=?', (data.name,)).fetchone():
            raise HTTPException(409, 'An Area with this name already exists')
        uid = conn.execute("INSERT INTO areas(name,latitude,longitude,default_zoom,is_active) VALUES (?,?,?,?,?)", tuple(data.model_dump().values())).lastrowid
        return {"id": uid}


@admin_router.put("/areas/{area_id}")
def edit_area(area_id: int, data: AreaIn, request: Request):
    with get_db() as conn:
        require_admin(request, conn)
        if not conn.execute('SELECT 1 FROM areas WHERE id=?', (area_id,)).fetchone():
            raise HTTPException(404, 'Area not found')
        if conn.execute('SELECT 1 FROM areas WHERE name=? AND id<>?', (data.name,area_id)).fetchone():
            raise HTTPException(409, 'An Area with this name already exists')
        conn.execute("UPDATE areas SET name=?,latitude=?,longitude=?,default_zoom=?,is_active=? WHERE id=?", (*data.model_dump().values(), area_id))
    return {"ok": True}


class Assignment(BaseModel):
    role: str
    area_ids: list[int] = Field(default_factory=list)
    default_area_id: int | None = None


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=100)
    password: str | None = Field(default=None, max_length=256)
    is_active: bool = True
    must_change_password: bool = True
    assignments: list[Assignment]


@admin_router.get("/users")
def users(request: Request):
    with get_db() as conn:
        require_admin(request, conn)
        result = [dict(r) for r in conn.execute("SELECT id,username,display_name,is_active,must_change_password FROM users ORDER BY username")]
        for u in result:
            u["assignments"] = []
            for r in conn.execute("SELECT role FROM user_roles WHERE user_id=?", (u["id"],)):
                aa = conn.execute("SELECT area_id,is_default FROM user_role_areas WHERE user_id=? AND role=?", (u["id"], r[0])).fetchall()
                u["assignments"].append({"role": r[0], "area_ids": [a[0] for a in aa], "default_area_id": next((a[0] for a in aa if a[1]), None)})
        return result


def save_user(conn, data, actor, uid=None):
    if not data.username.strip() or not data.display_name.strip():
        raise HTTPException(422, 'Username and display name are required')
    if conn.execute('SELECT 1 FROM users WHERE username=? AND id<>?', (data.username.strip(),uid or 0)).fetchone():
        raise HTTPException(409, 'Username is already in use')
    roles = [a.role for a in data.assignments]
    if not roles or len(set(roles)) != len(roles) or any(r not in ROLES for r in roles):
        raise HTTPException(422, "Choose one or more unique roles")
    for a in data.assignments:
        if a.role == "admin":
            if a.area_ids:
                raise HTTPException(422, "Admin does not have operational Areas")
            continue
        if not a.area_ids or a.default_area_id not in a.area_ids:
            raise HTTPException(422, "Each workspace requires Areas and a default Area")
        for aid in a.area_ids:
            if not conn.execute("SELECT 1 FROM areas WHERE id=? AND is_active=1", (aid,)).fetchone():
                raise HTTPException(422, "Select active Areas")
    if uid:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            raise HTTPException(404, "User not found")
        if not data.is_active or "admin" not in roles:
            admins = conn.execute("SELECT u.id FROM users u JOIN user_roles r ON r.user_id=u.id WHERE u.is_active=1 AND r.role='admin' AND u.id<>?", (uid,)).fetchall()
            if not admins:
                raise HTTPException(422, "Keep at least one active administrator")
        conn.execute("UPDATE users SET username=?,display_name=?,is_active=?,must_change_password=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (data.username.strip(), data.display_name, data.is_active, data.must_change_password, uid))
        conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM user_role_areas WHERE user_id=?", (uid,))
        conn.execute("DELETE FROM user_roles WHERE user_id=?", (uid,))
    else:
        if not data.password:
            raise HTTPException(422, "Temporary password is required")
        require_password(data.password)
        uid = conn.execute("INSERT INTO users(username,display_name,password_hash,is_active,must_change_password) VALUES (?,?,?,?,?)", (data.username.strip(),data.display_name,password_hash(data.password),data.is_active,data.must_change_password)).lastrowid
    if data.password:
        require_password(data.password)
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(data.password),uid))
    for a in data.assignments:
        conn.execute("INSERT INTO user_roles VALUES (?,?)", (uid,a.role))
        for aid in set(a.area_ids):
            conn.execute("INSERT INTO user_role_areas VALUES (?,?,?,?)", (uid,a.role,aid,int(aid==a.default_area_id)))
    conn.execute("INSERT INTO account_audit(actor_id,action,target_id) VALUES (?,?,?)", (actor["id"],"save_user",uid))
    return {"id":uid}


@admin_router.post("/users")
def create_user(data: UserIn, request: Request):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return save_user(conn,data,require_admin(request,conn))


@admin_router.put("/users/{user_id}")
def update_user(user_id: int, data: UserIn, request: Request):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        return save_user(conn,data,require_admin(request,conn),user_id)


@admin_router.get('/clinic-areas')
def clinic_areas(request: Request):
    with get_db() as conn:
        require_admin(request, conn)
        # Deliberately restricted provisioning metadata, not operational profiles.
        return [dict(r) for r in conn.execute('SELECT id,name,city,area_id FROM clinics ORDER BY name')]


class ClinicAreaIn(BaseModel):
    area_id: int


@admin_router.put('/clinic-areas/{clinic_id}')
def assign_clinic_area(clinic_id: int, data: ClinicAreaIn, request: Request):
    with get_db() as conn:
        user = require_admin(request, conn)
        if not conn.execute('SELECT 1 FROM areas WHERE id=? AND is_active=1', (data.area_id,)).fetchone():
            raise HTTPException(422, 'Select an active Area')
        cur = conn.execute('UPDATE clinics SET area_id=? WHERE id=?', (data.area_id,clinic_id))
        if not cur.rowcount:
            raise HTTPException(404,'Clinic not found')
        conn.execute('INSERT INTO account_audit(actor_id,action,target_id) VALUES (?,?,?)',(user['id'],'assign_clinic_area',clinic_id))
    return {'ok':True}
