"""
Think4U: Server-Timing 中介層
回傳 X-Server-Time header，瀏覽器 DevTools Network 可看每個請求的 server 處理時間。
"""
import time


class ServerTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        ms = (time.perf_counter() - start) * 1000
        response["X-Server-Time"] = f"{ms:.1f}ms"
        response["Server-Timing"] = f"app;dur={ms:.1f}"
        return response
