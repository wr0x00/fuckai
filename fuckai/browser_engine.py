# -*- coding: utf-8 -*-
"""内嵌浏览器引擎 —— 真实 Chromium（Blink）无头渲染。

「AI Safety HOT」面板不再用 iframe/代理：后端用 Playwright 驱动一个真实的
无头 Chromium 渲染页面，前端把画面当视频流看，交互（点击/滚轮/按键/导航）
转发给引擎。站点的暗色模式、客户端路由、一切按钮都是真实浏览器行为，
天然不存在防嵌入拦截、脚本剥离、跳转逃逸这些问题。

流畅性关键：不走「轮询截图」（每帧一次 CDP 往返，150~300ms，必卡顿），
而是用 CDP Page.startScreencast 让内核**在页面重绘时主动推帧**——事件驱动，
页面静止时零开销，滚动/动画时帧率自动跟上。

单例管理：服务启动即预热，进程退出时自动清理。
"""
from __future__ import annotations

import asyncio
import base64
import os
import time

from playwright.async_api import async_playwright

DEFAULT_URL = "https://aisafetyhot.com/zh"
VIEWPORT = {"width": 1280, "height": 800}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
GOTO_TIMEOUT = 45000
# 无损 PNG：JPEG 的 4:2:0 色度抽样会把文字边缘压糊，保真优先选 PNG
FRAME_FORMAT = "png"
# screencast 上限给足（4K），视口自适应缩放时无需重启串流
CAST_MAX_W = 3840
CAST_MAX_H = 2160
# 无人观看超过该秒数后自动关闭浏览器释放内存（0 = 永不回收）
IDLE_SUSPEND_SECS = int(os.environ.get("HOT_IDLE_SUSPEND_SECS", "300"))

# 内存瘦身：限制 V8 堆 / 收窄渲染进程 / 关磁盘缓存；防节流三项保证观看时满速渲染
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--js-flags=--max-old-space-size=192",
    "--renderer-process-limit=1",
    "--disable-features=site-per-process",
    "--disable-dev-shm-usage",
    "--disk-cache-size=1",
    "--media-cache-size=1",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]


class BrowserEngine:
    """惰性启动的单页 Chromium。所有方法需在事件循环内 await 调用。"""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._lock = asyncio.Lock()
        # 2x 超采样渲染：串流帧按 CSS 尺寸 2 倍编码，显示端下采样后清晰锐利
        self._dpr = 2.0
        # 前端报告的期望视口（引擎尚未启动时先存着，创建时生效）
        self._want = None
        # screencast 最新帧缓存
        self._frame = b""
        self._frame_seq = 0
        self._frame_event = asyncio.Event()
        # 闲置回收：观看者计数 + 最近使用时间 + 上次访问页
        self._clients = 0
        self._last_used = time.time()
        self._last_url: str | None = None
        self._watchdog_started = False

    @property
    def ready(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    @property
    def frame_seq(self) -> int:
        return self._frame_seq

    @property
    def clients(self) -> int:
        return self._clients

    # ---------- 闲置回收 ----------

    def client_enter(self) -> None:
        self._clients += 1
        self._last_used = time.time()

    def client_leave(self) -> None:
        self._clients = max(0, self._clients - 1)
        self._last_used = time.time()

    async def suspend(self) -> None:
        """关闭整只浏览器释放内存（保留 Playwright 驱动，下次按需拉起）。"""
        async with self._lock:
            if self._page is not None and not self._page.is_closed():
                self._last_url = self._page.url
            for closer in (self._context, self._browser):
                if closer is None:
                    continue
                try:
                    await closer.close()
                except Exception:
                    pass
            self._page = None
            self._context = None
            self._browser = None
            self._cdp = None
            self._frame = b""
            self._frame_seq = 0
            self._frame_event.clear()

    def _start_watchdog(self) -> None:
        if self._watchdog_started or IDLE_SUSPEND_SECS <= 0:
            self._watchdog_started = True
            return
        self._watchdog_started = True

        async def watchdog():
            while True:
                await asyncio.sleep(30)
                if (self._clients == 0 and self.ready
                        and time.time() - self._last_used >= IDLE_SUSPEND_SECS):
                    try:
                        await self.suspend()
                    except Exception:
                        pass

        asyncio.create_task(watchdog())

    # ---------- screencast ----------

    async def _start_screencast(self, page) -> None:
        """在页面 attached 后启动 CDP 串流：重绘即推帧。"""
        try:
            cdp = await page.context.new_cdp_session(page)
            self._cdp = cdp

            def on_frame(frame: dict) -> None:
                data = frame.get("data", "")
                if data:
                    try:
                        self._frame = base64.b64decode(data)
                        self._frame_seq += 1
                        self._frame_event.set()
                    except Exception:
                        pass
                # 必须及时 ack，内核才会推下一帧
                try:
                    asyncio.ensure_future(cdp.send(
                        "Page.screencastFrameAck",
                        {"sessionId": frame.get("sessionId")}))
                except Exception:
                    pass

            cdp.on("Page.screencastFrame", on_frame)
            cast_params = {
                "format": FRAME_FORMAT,
                "maxWidth": CAST_MAX_W,
                "maxHeight": CAST_MAX_H,
                "everyNthFrame": 1,
            }
            await cdp.send("Page.startScreencast", cast_params)
        except Exception:
            self._cdp = None  # 串流失败时回退到逐帧截图

    async def wait_frame(self, timeout: float = 0.5):
        """等一帧新画面；超时返回当前缓存帧。返回 (jpeg_bytes, seq)。"""
        if not self._frame_event.is_set():
            try:
                await asyncio.wait_for(self._frame_event.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        self._frame_event.clear()
        return self._frame, self._frame_seq

    async def latest_frame(self) -> bytes:
        return self._frame

    async def screenshot_frame(self) -> bytes:
        """回退路径：主动截一帧（慢，仅在串流不可用时用）。"""
        page = await self.page()
        return await page.screenshot(type=FRAME_FORMAT)

    # ---------- 页面生命周期 ----------

    async def page(self):
        """拿到可用页面；首次调用会启动 Chromium 并打开默认站点。"""
        async with self._lock:
            if self._page is not None and not self._page.is_closed():
                return self._page
            if self._pw is None:
                self._pw = await async_playwright().start()
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._pw.chromium.launch(
                    headless=True, args=LAUNCH_ARGS)
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:
                    pass
            self._context = await self._browser.new_context(
                viewport=(self._want or VIEWPORT), locale="zh-CN",
                user_agent=UA, device_scale_factor=self._dpr)
            self._want = None
            self._page = await self._context.new_page()
            self._frame = b""
            self._frame_seq = 0
            self._frame_event.clear()
            asyncio.create_task(self._start_screencast(self._page))
            self._start_watchdog()
            try:
                await self._page.goto(self._last_url or DEFAULT_URL,
                                      wait_until="domcontentloaded",
                                      timeout=GOTO_TIMEOUT)
                self._last_url = None
            except Exception:
                pass  # 默认页加载失败不阻塞引擎启动，用户可手动导航
            return self._page

    async def navigate(self, url: str) -> str:
        page = await self.page()
        await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT)
        return page.url

    async def reload(self) -> str:
        page = await self.page()
        try:
            await page.reload(wait_until="domcontentloaded", timeout=GOTO_TIMEOUT)
        except Exception:
            pass
        return page.url

    async def back(self) -> str:
        page = await self.page()
        try:
            await page.go_back(timeout=GOTO_TIMEOUT)
        except Exception:
            pass
        if page.url in ("about:blank", ""):  # 已退到新页历史起点，回默认站点
            try:
                await page.goto(DEFAULT_URL, wait_until="domcontentloaded",
                                timeout=GOTO_TIMEOUT)
            except Exception:
                pass
        return page.url

    async def forward(self) -> str:
        page = await self.page()
        try:
            await page.go_forward(timeout=GOTO_TIMEOUT)
        except Exception:
            pass
        return page.url

    # ---------- 交互 ----------

    async def resize(self, width: float, height: float, dpr: float | None = None) -> dict:
        """视口自适应：面板盒子多大，引擎视口就多大（CSS 像素），画面与 UI 1:1 对齐。"""
        width = int(max(360, min(CAST_MAX_W, width)))
        height = int(max(240, min(CAST_MAX_H, height)))
        if dpr:
            self._dpr = max(1.0, min(2.0, float(dpr)))
        if not self.ready:
            self._want = {"width": width, "height": height}
            return {"width": width, "height": height, "applied": False}
        page = await self.page()
        cur = page.viewport_size or {}
        if abs(cur.get("width", 0) - width) < 2 and abs(cur.get("height", 0) - height) < 2:
            return {"width": width, "height": height, "applied": True}
        await page.set_viewport_size({"width": width, "height": height})
        return {"width": width, "height": height, "applied": True}

    async def viewport_size(self) -> dict:
        if not self.ready:
            return dict(self._want or VIEWPORT)
        return dict(self._page.viewport_size or VIEWPORT)

    async def click(self, x: float, y: float) -> None:
        page = await self.page()
        vp = page.viewport_size or VIEWPORT
        await page.mouse.click(max(0, min(vp["width"], x)),
                               max(0, min(vp["height"], y)))

    async def scroll(self, dy: float) -> None:
        page = await self.page()
        await page.mouse.wheel(0, max(-2000, min(2000, dy)))

    async def key(self, key: str) -> None:
        """单字符按输入发送，其余（Enter/Backspace/ArrowUp…）按键名发送。"""
        page = await self.page()
        if len(key) == 1:
            await page.keyboard.type(key)
        else:
            await page.keyboard.press(key)

    async def insert_text(self, text: str) -> None:
        """整段文本注入（中文/粘贴专用）：走 CDP Input.insertText，完整支持 Unicode，
        绕开 host 输入法 composition 事件无法经 keydown 转发的限制。"""
        page = await self.page()
        await page.keyboard.insert_text(text)

    async def get_selection(self) -> str:
        """取引擎页面里当前选中的文本（配合 Ctrl+C 复制回 host 剪贴板）。"""
        page = await self.page()
        try:
            return await page.evaluate(
                "() => (window.getSelection ? String(window.getSelection()) : '')")
        except Exception:
            return ""

    async def current_url(self) -> str:
        page = await self.page()
        return page.url

    async def shutdown(self) -> None:
        for closer in (self._context, self._browser):
            if closer is None:
                continue
            try:
                await closer.close()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._cdp = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None


engine = BrowserEngine()
