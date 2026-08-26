"""测试贝壳/链家人机验证自动通过功能（极验点选）。

用法:
    uv run python -m houseprice.scripts.test_captcha

流程:
    1. 打开 hip.ke.com 验证页（直接传入带 location 的验证 URL）
    2. 复用 beike.is_captcha_required 自动过验证
    3. 等待跳转：验证通过后浏览器应跳回 location 指向的房源页，
       据此判定成功/失败，并以退出码返回结果（0=通过，1=未通过/失败）
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from houseprice.getdata.spiders.base import create_page
from houseprice.getdata.spiders.beike import is_captcha_required

CAPTCHA_URL = (
    "https://hip.ke.com/captcha?location=https%3A%2F%2Fnj.zu.ke.com%2Fzufang%2F"
    "NJ2052001271249895424.html%3Fnav%3D0%26unique_id%3D9cbf41d8-ab4c-4955-9823-"
    "31ec77703dafzufang1787619871602&ext=56ZL-bJjtgBFviOjv9a6-rHMOYlqPnk_N6M5S"
    "OtHIetX8w2J39LnjX-uPlwTFn1egQnqNqEz2GXgg0gQvjjyF8WgtrLt-7GrIUu_akq7Z4w"
    "xFqJmJlefBPkWBZnIAY9gmbx4ZWblo3Z26xZQPLvVK_zmmUnvG1t9esRkuS7oExHwqrh"
    "H4w_xMWjxMe0LYZ-9uv7E6fd-ROzPDVIPqxQNfebao85NwZm-9q4Qo3OzNHyc3D9ItKSBM"
    "1Su6s-DcmAmNp6jImTYoVKLQ9n0307l2JXS"
)

# 验证通过后应跳回的地址（解码 location 参数），如 https://nj.zu.ke.com/zufang/xxx.html
LOCATION = parse_qs(urlparse(CAPTCHA_URL).query)["location"][0]
# 跳回页的域名特征：比较主机名而非子串，避免命中验证页 URL 中 location 参数自带的域名
MARK = urlparse(LOCATION).netloc


def main() -> int:
    """执行自动验证测试，返回退出码（0=通过，1=未通过/失败）。"""
    page = create_page()
    try:
        page.get(CAPTCHA_URL)
        # 验证组件由 JS 异步初始化，先等「点击按钮开始验证」出现再交给
        # is_captcha_required（该函数内部对按钮只等 2s，首次打开验证页可能来不及）
        btn = page.ele("css:.geetest_btn_click", timeout=10)
        if not btn:
            print("[失败] 未出现「点击按钮开始验证」，可能未触发验证码或页面结构变化")
            return 1

        is_captcha_required(page)  # 复用贝壳自动过验证逻辑（点击->截图->打码->点选->确定）

        # 验证通过后 hip.ke.com 会跳回 location 指向的房源页，最多等 60s
        for _ in range(60):
            if urlparse(page.url).netloc == MARK:
                print(f"[成功] 验证通过，已跳回目标页：{page.url}")
                return 0
            page.wait(1)
        print(f"[失败] 等待跳转超时，当前 URL：{page.url}")
        return 1
    finally:
        page.quit()


if __name__ == "__main__":
    raise SystemExit(main())


