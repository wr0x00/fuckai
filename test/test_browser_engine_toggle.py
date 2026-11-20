from __future__ import annotations

import unittest

from fuckai.browser_engine import BrowserEngine


class _AsyncCloser:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _Page(_AsyncCloser):
    url = "https://example.invalid/"

    def is_closed(self):
        return self.closed


class _Context(_AsyncCloser):
    def __init__(self, page):
        super().__init__()
        self.page = page

    async def close(self):
        await super().close()
        self.page.closed = True


class _Playwright:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class BrowserEngineToggleTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabling_closes_browser_and_blocks_restart(self):
        engine = BrowserEngine()
        page = _Page()
        context = _Context(page)
        browser = _AsyncCloser()
        playwright = _Playwright()
        engine._page = page
        engine._context = context
        engine._browser = browser
        engine._pw = playwright

        await engine.set_enabled(False)

        self.assertFalse(engine.enabled)
        self.assertFalse(engine.ready)
        self.assertTrue(page.closed)
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await engine.page()

    async def test_enabling_allows_lazy_start(self):
        engine = BrowserEngine()
        await engine.set_enabled(False)
        await engine.set_enabled(True)

        self.assertTrue(engine.enabled)
        self.assertFalse(engine.ready)


if __name__ == "__main__":
    unittest.main()