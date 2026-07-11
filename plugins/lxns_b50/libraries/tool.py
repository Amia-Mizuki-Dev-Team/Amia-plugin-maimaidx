import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Union

import aiofiles
from nonebot.log import logger
from playwright.async_api import Error as PlaywrightError, async_playwright

from ..config import SNAPSHOT_JS, pie_html_file


def qqhash(qq: int):
    days = int(time.strftime("%d", time.localtime(time.time()))) + 31 * int(
        time.strftime("%m", time.localtime(time.time()))
    ) + 77
    return (days * qq) >> 8


async def openfile(file: Path) -> Union[dict, list]:
    async with aiofiles.open(file, "r", encoding="utf-8") as f:
        data = json.loads(await f.read())
    return data


async def writefile(file: Path, data: Any) -> bool:
    async with aiofiles.open(file, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=4))
    return True


async def _launch_browser(p):
    launch_errors = []
    browser = None

    executable_path = os.getenv("LXNS_PLAYWRIGHT_EXECUTABLE", "").strip()
    if executable_path:
        try:
            browser = await p.chromium.launch(
                executable_path=executable_path,
                headless=True,
            )
        except PlaywrightError as e:
            launch_errors.append(f"LXNS_PLAYWRIGHT_EXECUTABLE: {e}")

    if browser is None:
        for channel in ("msedge", "chrome"):
            try:
                browser = await p.chromium.launch(channel=channel, headless=True)
                break
            except PlaywrightError as e:
                launch_errors.append(f"{channel}: {e}")

    if browser is None:
        try:
            browser = await p.chromium.launch(headless=True)
        except PlaywrightError as e:
            launch_errors.append(f"playwright chromium: {e}")

    if browser is None:
        logger.error("Playwright 浏览器启动失败: " + " | ".join(launch_errors))
        raise RuntimeError(
            "无法启动浏览器渲染图片。请安装 Microsoft Edge/Chrome，"
            "或执行 playwright install chromium，"
            "或设置 LXNS_PLAYWRIGHT_EXECUTABLE 指向 chrome.exe。"
        )

    return browser


async def run_chrome_to_base64() -> str:
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        page = await browser.new_page(java_script_enabled=True)
        await page.goto(pie_html_file.as_uri())
        await asyncio.sleep(2)
        snapshot_js = SNAPSHOT_JS.read_text(encoding="utf-8")
        content: str = await page.evaluate(snapshot_js)
        await browser.close()

    content_array = content.split(",")
    if len(content_array) != 2:
        raise OSError(content_array)

    return "base64://" + content_array[-1]


async def render_html_card_to_base64(
    html: str,
    selector: str = "#card-root",
    width: int = 768,
    height: int = 1052,
) -> str:
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        page = await browser.new_page(java_script_enabled=True)
        await page.set_viewport_size({"width": width, "height": height})
        await page.set_content(html, wait_until="load")
        content = await page.locator(selector).screenshot(type="png")
        await browser.close()

    return "base64://" + base64.b64encode(content).decode("ascii")
