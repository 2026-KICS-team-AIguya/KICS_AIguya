"""공식 식단표 수집과 캐시 관리."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
KST = timezone(timedelta(hours=9))
CACHE_SECONDS = 3600
MIN_REFRESH_SECONDS = 60
SOURCES = {
    "sangnok": {"name": "상록원", "label": "동국대학교 생활협동조합", "url": "https://dgucoop.dongguk.edu:44649/store/store.php?w=4&l=2"},
    "dormitory": {"name": "기숙사 식당", "label": "동국대학교 남산학사", "url": "https://dorm.dongguk.edu/article/food/list"},
    "business": {"name": "경영관", "label": "동국대학교 D-Flex 식당", "url": "https://www.dongguk.edu/article/FOODDFLEX/list"},
}
ALLOWED_ORIGINS = {("www.dongguk.edu", 443), ("dorm.dongguk.edu", 443), ("dgucoop.dongguk.edu", 44649)}
VOID_TAGS = {"img", "br", "input", "meta", "link", "hr", "source", "area", "wbr", "embed", "param", "col"}


class Node:
    def __init__(self, tag="root", attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs or []), parent
        self.children = []

    def walk(self, tag=None):
        if tag is None or self.tag == tag:
            yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk(tag)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def find_class(self, name):
        return next((node for node in self.walk() if node.has_class(name)), None)

    def ancestor(self, tag):
        node = self.parent
        while node is not None and node.tag != tag:
            node = node.parent
        return node

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        if self.tag == "br":
            return "\n"
        result = "".join(child.text() if isinstance(child, Node) else child for child in self.children)
        return result + ("\n" if self.tag in {"div", "p", "td", "li"} else "")


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean_text(value):
    return re.sub(r"\s+", " ", value).strip()


def date_range(text):
    matches = re.findall(r"(?<!\d)(\d{4}|\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})(?!\d)", text)
    if len(matches) < 2:
        return None
    try:
        values = [date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day)) for year, month, day in matches[:2]]
    except ValueError:
        return None
    if values[1] < values[0] or (values[1] - values[0]).days > 14:
        return None
    return values[0], values[1]


def safe_url(url, base=None):
    absolute = urljoin(base, url.strip()) if base else url.strip()
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("Only public official HTTPS sources are supported")
    if (parsed.hostname, parsed.port or 443) not in ALLOWED_ORIGINS:
        raise ValueError("Unsupported menu source")
    return absolute


def download(url, limit=2_000_000):
    url = safe_url(url)
    # 리다이렉트도 공식 도메인인지 확인한다.
    for _ in range(4):
        with requests.get(url, timeout=(5, 12), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = safe_url(response.headers["Location"], url)
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Menu resource is too large")
                chunks.append(chunk)
            return b"".join(chunks), url
    raise ValueError("Too many redirects")


def read_html(url):
    content, final_url = download(url)
    encoding = "cp949" if urlparse(final_url).hostname == "dgucoop.dongguk.edu" else "utf-8"
    html = content.decode(encoding, errors="replace")
    if "Please prove that you are human" in html:
        raise ValueError("Official site requires human verification")
    return Document(html).root, final_url


def table_rows(table):
    """중첩 표를 제외하고 병합 셀을 펼친다."""
    pending = {}
    for row in table.walk("tr"):
        if row.ancestor("table") is not table:
            continue
        cells = [child for child in row.children if isinstance(child, Node) and child.tag in {"td", "th"}]
        grid = {column: node for column, (node, _) in pending.items()}
        next_pending = {column: (node, remaining - 1) for column, (node, remaining) in pending.items() if remaining > 1}
        column = 0
        for cell in cells:
            while column in grid:
                column += 1
            colspan = min(50, max(1, int(cell.attrs.get("colspan", 1))))
            rowspan = min(50, max(1, int(cell.attrs.get("rowspan", 1))))
            for offset in range(colspan):
                grid[column + offset] = cell
                if rowspan > 1:
                    next_pending[column + offset] = (cell, rowspan - 1)
            column += colspan
        pending = next_pending
        yield cells, [grid.get(index) for index in range(max(grid, default=-1) + 1)]


def parse_sangnok(root):
    period_node = next((node for node in root.walk() if node.has_class("menu_date") and date_range(node.text())), None)
    if period_node is None:
        raise ValueError("Weekly menu dates were not found")
    start, end = date_range(period_node.text())
    if (end - start).days != 6:
        raise ValueError("Expected seven days in the cooperative weekly table")
    heading = next((node for node in root.walk("td") if node.has_class("menu_st")), None)
    table = heading.ancestor("table") if heading else None
    if table is None:
        raise ValueError("Weekly menu table was not found")
    days = [{"date": (start + timedelta(days=index)).isoformat(), "entries": []} for index in range(7)]
    floor = None
    for cells, grid in table_rows(table):
        section = next((cell for cell in cells if cell.has_class("menu_st")), None)
        if section is not None:
            match = re.search(r"상록원\s*([123])\s*층", clean_text(section.text()))
            floor = int(match.group(1)) if match else None
            continue
        if floor is None or len(grid) != 9 or not grid[0] or not grid[1]:
            continue
        corner = re.sub(r"\s+", "", grid[0].text())
        meal = clean_text(grid[1].text())
        general_menu = grid[0] is grid[1] and corner == "메뉴"
        if not general_menu and meal not in {"조식", "중식", "석식", "중·석식", "중석식"}:
            continue
        for index, cell in enumerate(grid[2:]):
            if cell is None:
                continue
            lines = [clean_text(line) for line in cell.text().splitlines() if clean_text(line)]
            if not lines:
                continue
            price, body = None, []
            for line in lines:
                # 여러 가격이 섞인 메뉴 본문은 그대로 둔다.
                match = re.fullmatch(r"[￦₩]\s*([\d,]+)", line)
                if match:
                    price = f"{int(match.group(1).replace(',', '')):,}원"
                else:
                    body.append(line)
            if body:
                menu_corner = body[0].strip("* ") if general_menu else corner
                menu_body = body[1:] if general_menu and body[0].startswith("*") else body
                days[index]["entries"].append({"floor": floor, "corner": menu_corner, "meal": "메뉴" if general_menu else meal, "lines": menu_body, "price": price})
    if not any(day["entries"] for day in days):
        raise ValueError("No published Sangnokwon menu entries were found")
    return {"format": "table", "title": "상록원 주간 식단", "periodStart": start.isoformat(), "periodEnd": end.isoformat(), "days": days, "images": [], "attachments": []}


def find_posts(root, base_url):
    posts = []
    for anchor in root.walk("a"):
        title_node = next(anchor.walk("p"), None)
        title = clean_text((title_node or anchor).text())
        period = date_range(title)
        if "주간" not in title or "식단" not in title or period is None:
            continue
        href = anchor.attrs.get("href", "")
        if "/detail/" in href:
            url = safe_url(href, base_url)
        else:
            match = re.search(r"goDetail\((\d+)\)", anchor.attrs.get("onclick", ""))
            if not match:
                continue
            url = safe_url(base_url.split("/list")[0] + "/detail/" + match.group(1))
        posts.append({"title": title, "url": url, "start": period[0], "end": period[1]})
    return posts


def choose_post(posts, today):
    if not posts:
        raise ValueError("No dated weekly menu posts were found")
    current = [post for post in posts if post["start"] <= today <= post["end"]]
    return max(current or posts, key=lambda post: post["start"])


def image_extension(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif content.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    elif content.startswith((b"GIF87a", b"GIF89a")):
        extension = "gif"
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        extension = "webp"
    else:
        raise ValueError("Unsupported menu image format")
    return extension


def store_image(url, web_root):
    content, final_url = download(url, limit=8_000_000)
    extension = image_extension(content)
    name = hashlib.sha256(content).hexdigest()[:16] + "." + extension
    directory = web_root / "assets" / "menus"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        target.write_bytes(content)
    return {"path": f"assets/menus/{name}", "sourceUrl": final_url}


def collect_board(location_id, today, web_root, image_store=store_image):
    source = SOURCES[location_id]
    root, list_url = read_html(source["url"])
    post = choose_post(find_posts(root, list_url), today)
    detail, detail_url = read_html(post["url"])
    content = detail.find_class("view_cont")
    if content is None:
        raise ValueError("The official post body was not found")
    images = []
    for image in content.walk("img"):
        if image.attrs.get("src"):
            images.append(image_store(safe_url(image.attrs["src"], detail_url), web_root))
    if not images:
        raise ValueError("The weekly menu image was not found")
    attachments = []
    files = detail.find_class("view_files")
    for anchor in files.walk("a") if files else []:
        href = anchor.attrs.get("href", "").strip()
        js_download = re.search(r"downGO\('([^']*)','([^']*)','([^']*)'\)", href)
        if js_download:
            filename, path, realname = js_download.groups()
            href = "/cmmn/fileDown.do?" + urlencode({"filename": filename, "filepath": path, "filerealname": realname})
        if href.startswith("/"):
            attachments.append({"label": clean_text(anchor.text()), "url": safe_url(href, detail_url)})
    return {"format": "image", "title": post["title"], "periodStart": post["start"].isoformat(), "periodEnd": post["end"].isoformat(), "days": [], "images": images, "attachments": attachments, "sourceUrl": detail_url}


def collect_location(location_id, now, web_root, image_store=store_image):
    source = SOURCES[location_id]
    if location_id == "sangnok":
        root, _ = read_html(source["url"])
        result = parse_sangnok(root)
    else:
        result = collect_board(location_id, now.date(), web_root, image_store)
    return {"locationId": location_id, "status": "ready", "sourceLabel": source["label"], "sourceUrl": source["url"], "fetchedAt": now.isoformat(), **result}


class MenuService:
    def __init__(self, web_root=WEB_ROOT, persist=True, image_store=None):
        self.web_root = Path(web_root)
        self.persist = persist
        self.image_store = image_store
        self.lock = threading.Lock()
        self.cache = None

    def load(self):
        if self.cache is None:
            try:
                self.cache = json.loads((self.web_root / "menus.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {"version": 1, "generatedAt": None, "locations": {}}
        return self.cache

    def refresh(self, force=False):
        with self.lock:
            now = datetime.now(KST)
            cache = self.load()
            if self._is_fresh(cache, now, force):
                return cache

            catalog = {
                "version": 1,
                "generatedAt": now.isoformat(),
                "locations": self._collect(cache.get("locations", {}), now),
            }
            if self.persist:
                self._save(catalog)
            self.cache = catalog
            return catalog

    @staticmethod
    def _is_fresh(cache, now, force):
        try:
            age = (now - datetime.fromisoformat(cache["generatedAt"])).total_seconds()
        except (TypeError, ValueError):
            age = CACHE_SECONDS
        interval = MIN_REFRESH_SECONDS if force else CACHE_SECONDS
        return 0 <= age < interval

    def _collect(self, previous, now):
        results = {}
        options = {"image_store": self.image_store} if self.image_store else {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                key: pool.submit(collect_location, key, now, self.web_root, **options)
                for key in SOURCES
            }
            for key, future in futures.items():
                try:
                    results[key] = future.result()
                except Exception as error:
                    results[key] = self._failed_menu(key, previous.get(key), now)
                    print(f"menu source {key}: {type(error).__name__}: {str(error)[:180]}")
        return results

    @staticmethod
    def _failed_menu(location_id, previous, now):
        source = SOURCES[location_id]
        fallback = previous or {
            "locationId": location_id, "format": None,
            "days": [], "images": [], "attachments": [],
            "sourceUrl": source["url"], "sourceLabel": source["label"], "fetchedAt": None,
        }
        return {
            **fallback,
            "status": "stale" if previous and previous.get("fetchedAt") else "error",
            "lastCheckedAt": now.isoformat(),
            "message": "최신 식단표를 확인하지 못했습니다. 공식 안내를 확인해 주세요.",
        }

    def _save(self, catalog):
        self.web_root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(catalog, ensure_ascii=False, indent=2)
        script_data = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        files = {"menus.json": payload, "menu-cache.js": f"window.DINING_MENU_CACHE = {script_data};\n"}
        for filename, content in files.items():
            temporary = self.web_root / (filename + ".tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(self.web_root / filename)


menu_service = MenuService()
