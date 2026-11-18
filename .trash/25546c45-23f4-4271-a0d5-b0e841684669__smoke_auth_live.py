"""联调冒烟：真实 HTTP 走一遍登录/权限/刷新/注销（联调后即可删除）。"""

from __future__ import annotations

import json

import requests

BASE = "http://127.0.0.1:8012"


def show(label, resp):
    body = ""
    try:
        body = json.dumps(resp.json(), ensure_ascii=False)[:160]
    except ValueError:
        body = resp.text[:160]
    print(f"{label:42s} {resp.status_code}  {body}")


s = requests.Session()

show("GET /health (匿名)", s.get(f"{BASE}/health"))
show("GET /auth/status (匿名)", s.get(f"{BASE}/auth/status"))
show("GET /predict/top-risk (匿名，应 401)", s.get(f"{BASE}/predict/top-risk"))
show("GET /users (匿名，应 401)", s.get(f"{BASE}/users"))

r = s.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin12345"})
show("POST /auth/login (admin)", r)
token = r.json()["access_token"]
refresh = r.json()["refresh_token"]
auth = {"Authorization": f"Bearer {token}"}

show("GET /auth/me (admin)", s.get(f"{BASE}/auth/me", headers=auth))
show("GET /users (admin，应 200)", s.get(f"{BASE}/users", headers=auth))

create = s.post(
    f"{BASE}/users",
    headers=auth,
    json={"username": "smoke_analyst", "password": "Sm0kePass!2026", "role": "analyst"},
)
show("POST /users 建分析师", create)

r2 = s.post(f"{BASE}/auth/login", json={"username": "smoke_analyst", "password": "Sm0kePass!2026"})
show("POST /auth/login (analyst)", r2)
analyst_auth = {"Authorization": f"Bearer {r2.json()['access_token']}"}

show("GET /users (analyst，应 403)", s.get(f"{BASE}/users", headers=analyst_auth))
show("GET /auth/me (analyst)", s.get(f"{BASE}/auth/me", headers=analyst_auth))

show("POST /auth/refresh", s.post(f"{BASE}/auth/refresh", json={"refresh_token": refresh}))
show("POST /auth/refresh 重放旧令牌（应 401）",
     s.post(f"{BASE}/auth/refresh", json={"refresh_token": refresh}))
show("POST /auth/logout", s.post(f"{BASE}/auth/logout", headers=auth, json={"refresh_token": ""}))
show("GET /auth/me 注销后（应 401）", s.get(f"{BASE}/auth/me", headers=auth))
show("GET /audit/logs (admin 已注销，应 401)", s.get(f"{BASE}/audit/logs", headers=auth))

r3 = s.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin12345"})
admin_auth = {"Authorization": f"Bearer {r3.json()['access_token']}"}
show("GET /audit/logs (重新登录 admin)", s.get(f"{BASE}/audit/logs?size=3", headers=admin_auth))
show("GET /audit/summary", s.get(f"{BASE}/audit/summary", headers=admin_auth))