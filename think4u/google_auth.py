"""
think4u/google_auth.py — Google SSO（OAuth 2.0 Authorization Code Flow）

輕量實作，不引入 django-allauth：
  1. /think4u/google/login/    → 產生 state 存 session，重導向 Google 授權頁
  2. /think4u/google/callback/ → 驗 state、以 code 換 token、解析 id_token 取 email
                                 → 以 email 對應既有 User（username 即 email）→ login()

安全性：
  - state 隨機 token 存 session，callback 驗證（防 CSRF）。
  - id_token 由本伺服器直接向 Google token endpoint（TLS）換得，
    依 Google 官方文件此情境可免驗簽章；仍驗 iss / aud / email_verified。
  - 僅允許「既有帳號」登入（email 對不到 User → 拒絕），不自動建帳號。
  - 可選網域白名單 GOOGLE_OAUTH_ALLOWED_DOMAINS（預設 think4u-tech.com）。

設定（.env）：
  GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET —— 未設定時登入頁不顯示按鈕。
Google Cloud Console 需登記的 Redirect URI（每個使用網域各一筆）：
  http://localhost:8001/think4u/google/callback/
  https://<你的 ngrok 網域>/think4u/google/callback/
"""
import base64
import json
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_KEY = "t4u_google_state"
_DEST_KEY = "t4u_google_dest"


def _redirect_uri(request) -> str:
    """組 callback 絕對網址；非 localhost（ngrok / 正式站）強制 https
    （DEBUG 下 Django 看不到 X-Forwarded-Proto，會誤判 http）。"""
    uri = request.build_absolute_uri(reverse("think4u-google-callback"))
    host = request.get_host().split(":")[0]
    if host not in ("localhost", "127.0.0.1") and uri.startswith("http://"):
        uri = "https://" + uri[len("http://"):]
    return uri


def _resolve_destination(user, dest: str) -> str:
    """與 base.views.login_user 相同的前台/後台導向規則。"""
    from think4u.models import user_can_access_admin, user_is_admin_only

    if user_is_admin_only(user):
        return "/"
    if dest == "portal":
        return "/portal/"
    if dest == "admin":
        return "/" if user_can_access_admin(user) else "/portal/"
    return "/" if user_can_access_admin(user) else "/portal/"


def _decode_id_token_payload(id_token: str) -> dict:
    """取 JWT payload（不驗簽 — token 直接來自 Google token endpoint over TLS）。"""
    try:
        payload_b64 = id_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # base64 padding
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}


def google_login(request):
    """導向 Google OAuth 授權頁。?dest=portal|admin 記在 session，callback 後沿用。"""
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    if not client_id:
        messages.error(request, _("Google sign-in is not configured."))
        return redirect("login")

    state = secrets.token_urlsafe(32)
    request.session[_STATE_KEY] = state
    dest = request.GET.get("dest", "")
    if dest in ("portal", "admin"):
        request.session[_DEST_KEY] = dest
    else:
        request.session.pop(_DEST_KEY, None)

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    domains = getattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAINS", [])
    if len(domains) == 1:
        params["hd"] = domains[0]  # 提示 Google 預選公司網域（僅 UX，仍需後端驗證）
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


def google_callback(request):
    """Google 授權回跳：驗 state → 換 token → 取 email → 對應既有 User → login。"""
    # 使用者在 Google 頁面按取消等
    if request.GET.get("error"):
        messages.error(request, _("Google sign-in was cancelled."))
        return redirect("login")

    state = request.GET.get("state", "")
    saved_state = request.session.pop(_STATE_KEY, None)
    dest = request.session.pop(_DEST_KEY, "")
    if not state or not saved_state or state != saved_state:
        messages.error(request, _("Google sign-in failed: invalid state."))
        return redirect("login")

    code = request.GET.get("code", "")
    if not code:
        messages.error(request, _("Google sign-in failed: missing code."))
        return redirect("login")

    try:
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_data = resp.json()
    except requests.RequestException:
        messages.error(request, _("Google sign-in failed: could not reach Google."))
        return redirect("login")

    id_token = token_data.get("id_token")
    if not id_token:
        messages.error(request, _("Google sign-in failed: no identity token."))
        return redirect("login")

    claims = _decode_id_token_payload(id_token)
    email = (claims.get("email") or "").strip().lower()
    if (
        claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
        or claims.get("aud") != settings.GOOGLE_OAUTH_CLIENT_ID
        or not claims.get("email_verified")
        or not email
    ):
        messages.error(request, _("Google sign-in failed: identity could not be verified."))
        return redirect("login")

    # 網域白名單（空清單 = 不限制；帳號本身仍須存在）
    domains = getattr(settings, "GOOGLE_OAUTH_ALLOWED_DOMAINS", [])
    if domains and email.split("@")[-1] not in domains:
        messages.error(request, _("This Google account's domain is not allowed."))
        return redirect("login")

    # 僅允許既有帳號（username 即 email；備援比對 User.email）— 不自動開帳號
    user = (
        User.objects.filter(username__iexact=email).first()
        or User.objects.filter(email__iexact=email).first()
    )
    if not user:
        messages.error(
            request, _("No account is linked to this Google email. Please contact HR.")
        )
        return redirect("login")
    if not user.is_active:
        messages.warning(request, _("Access Denied: Your account is blocked."))
        return redirect("login")

    employee = getattr(user, "employee_get", None)
    if employee is None:
        messages.error(
            request,
            _("An employee related to this user's credentials does not exist."),
        )
        return redirect("login")
    if not employee.is_active:
        messages.warning(
            request,
            _("This user is archived. Please contact the manager for more information."),
        )
        return redirect("login")

    login(request, user)
    messages.success(request, _("Login successful."))
    return redirect(_resolve_destination(user, dest))
