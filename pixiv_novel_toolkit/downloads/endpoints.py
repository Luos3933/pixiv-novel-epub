"""Pixiv 下载接口 URL 的集中定义。"""


PIXIV_AJAX_BASE = "https://www.pixiv.net/ajax"


def novel_detail_url(novel_id):
    return f"{PIXIV_AJAX_BASE}/novel/{novel_id}"


def illustration_detail_url(illustration_id):
    return f"{PIXIV_AJAX_BASE}/illust/{illustration_id}"


def series_overview_url(series_id):
    return f"{PIXIV_AJAX_BASE}/novel/series/{series_id}?lang=zh"


def series_content_url(series_id, page_limit, last_order):
    return (
        f"{PIXIV_AJAX_BASE}/novel/series_content/{series_id}"
        f"?limit={page_limit}&last_order={last_order}&order_by=asc&lang=zh"
    )
