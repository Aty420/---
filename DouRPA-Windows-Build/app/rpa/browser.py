from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Page

MERCHANT_HOME = "https://fxg.jinritemai.com/"


class BrowserManager:
    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def _launch(self, channel: str) -> BrowserContext:
        return self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel=channel,
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )

    def start(self) -> Page:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()

        last_error = None
        # Prefer system Edge so the installer does not need to bundle a large Chromium runtime.
        for channel in ("msedge", "chrome"):
            try:
                self.context = self._launch(channel)
                break
            except Exception as exc:
                last_error = exc
                self.context = None

        if self.context is None:
            self._pw.stop()
            self._pw = None
            raise RuntimeError(
                "未检测到可供 RPA 使用的 Microsoft Edge / Google Chrome。"
                "请先安装或更新 Microsoft Edge 后重试。\n\n"
                f"底层错误：{last_error}"
            )

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page

    def open_login(self):
        page = self.page or self.start()
        page.goto(MERCHANT_HOME, wait_until="domcontentloaded", timeout=60000)
        return page

    def stop(self):
        try:
            if self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()
        self.context = None
        self.page = None
        self._pw = None
