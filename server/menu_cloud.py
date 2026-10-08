"""Read-only menu collection and narrowly scoped image transport for Vercel."""
import re
from urllib.parse import parse_qs, urlencode, urlparse

from server.menu_service import MenuService, download, image_extension, safe_url

IMAGE_FOLDERS = {
    "www.dongguk.edu": {"/ckeditor//FOODDFLEX", "/ckeditor/FOODDFLEX"},
    "dorm.dongguk.edu": {"/ckeditor//food", "/ckeditor/food"},
}


def official_image_url(value):
    url = safe_url(value)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if parsed.hostname not in IMAGE_FOLDERS or parsed.path != "/cmmn/fileView":
        raise ValueError("Unsupported menu image endpoint")
    if set(query) != {"path", "physical", "contentType"} or any(len(values) != 1 for values in query.values()):
        raise ValueError("Unsupported menu image parameters")
    if query["path"][0] not in IMAGE_FOLDERS[parsed.hostname] or query["contentType"][0] != "image":
        raise ValueError("Unsupported menu image folder")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}\.(png|jpe?g|gif|webp)", query["physical"][0], re.IGNORECASE):
        raise ValueError("Unsupported menu image name")
    return url


def cloud_image_descriptor(url, web_root):
    url = official_image_url(url)
    return {"path": "/api/menu-image?" + urlencode({"source": url}), "sourceUrl": url}


def fetch_menu_image(url):
    content, _ = download(official_image_url(url), limit=4_000_000)
    extension = image_extension(content)
    mime = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}[extension]
    return content, mime


cloud_menu_service = MenuService(persist=False, image_store=cloud_image_descriptor)
