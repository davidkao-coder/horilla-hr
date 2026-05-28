"""
think4u/admin_gate_middleware.py — 後台存取守門員

已登入但訪問後台路徑時，若不在 AdminAccessGroup 內就導到前台 /portal/。

被視為「前台 / 公開」可不被擋的路徑前綴：
  /portal/        — 員工自助
  /clock/         — 舊版打卡頁（保留向下相容）
  /login/         — 登入頁
  /logout/        — 登出
  /landing/       — 雙入口（仍保留）
  /static/, /media/ — 靜態檔
  /favicon.ico    — favicon
  /reload-messages/ — 訊息更新
"""
from django.shortcuts import redirect

from think4u.models import user_can_access_admin

# 前台 / 公開路徑前綴
ALLOWED_PREFIXES = (
    "/portal/",
    "/clock/",
    "/login/",
    "/logout/",
    "/landing/",
    "/static/",
    "/media/",
    "/favicon.ico",
    "/reload-messages",
    "/forgot-password",
    "/reset-password",
)


class AdminAccessGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path
            if not any(path.startswith(p) for p in ALLOWED_PREFIXES):
                if not user_can_access_admin(request.user):
                    # 已登入但無後台權限 → 導前台
                    return redirect("/portal/")
        return self.get_response(request)
