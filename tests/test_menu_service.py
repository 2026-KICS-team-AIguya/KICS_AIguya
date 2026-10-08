import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from server.menu_service import Document, MenuService, choose_post, date_range, parse_sangnok, safe_url


def week_cells(value):
    return "<td></td><td></td><td>" + value + "</td>" + "<td></td>" * 4


class MenuParsingTests(unittest.TestCase):
    def test_spans_floors_and_price_scope(self):
        html = '<span class="menu_date">2026.10.04 ~ 2026.10.10</span><table>'
        html += '<tr><td class="menu_st" colspan="9">상록원3층식당</td></tr>'
        html += '<tr><td rowspan="2">집<br>밥</td><td>중식</td>' + week_cells('김치찌개<br>(돼지:국내산)<br>￦ 7,000') + '</tr>'
        html += '<tr><td>석식</td>' + week_cells('비빔밥<br>￦ 7,000') + '</tr>'
        html += '<tr><td class="menu_st" colspan="9">상록원1층식당(솥앤누들)</td></tr>'
        html += '<tr><td rowspan="2" colspan="2">메 뉴</td>' + week_cells('****솥밥****<br>10:30~18:30<br>메뉴A 6,800원<br>메뉴B<br>7,000원') + '</tr>'
        html += '<tr>' + week_cells('****누들****<br>우동 5,500원') + '</tr>'
        html += '<tr><td class="menu_st" colspan="9">다른 캠퍼스 식당</td></tr>'
        html += '<tr><td>코너</td><td>중식</td>' + week_cells('포함하면 안 되는 메뉴') + '</tr></table>'
        result = parse_sangnok(Document(html).root)
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["days"][0]["entries"], [])
        entries = result["days"][2]["entries"]
        self.assertEqual([entry["floor"] for entry in entries], [3, 3, 1, 1])
        self.assertEqual(entries[1]["corner"], "집밥")
        self.assertEqual(entries[1]["meal"], "석식")
        self.assertEqual(entries[0]["price"], "7,000원")
        self.assertEqual(entries[2]["corner"], "솥밥")
        self.assertIsNone(entries[2]["price"])
        self.assertIn("7,000원", entries[2]["lines"])
        self.assertEqual(entries[3]["corner"], "누들")

    def test_current_post_wins_over_published_future_week(self):
        current = {"start": date(2026, 10, 5), "end": date(2026, 10, 9)}
        upcoming = {"start": date(2026, 10, 12), "end": date(2026, 10, 16)}
        self.assertIs(choose_post([upcoming, current], date(2026, 10, 6)), current)
        self.assertIs(choose_post([upcoming, current], date(2026, 10, 10)), upcoming)

    def test_date_validation_and_short_year(self):
        self.assertEqual(date_range('(26.10.05~26.10.09)'), (date(2026, 10, 5), date(2026, 10, 9)))
        self.assertIsNone(date_range('2026.10.99 ~ 2026.10.09'))
        self.assertIsNone(date_range('2026.10.09 ~ 2026.10.05'))

    def test_only_official_https_origins(self):
        self.assertEqual(safe_url('/cmmn/fileView?a=1', 'https://dorm.dongguk.edu/article/food/list'), 'https://dorm.dongguk.edu/cmmn/fileView?a=1')
        for url in ['http://dorm.dongguk.edu/', 'https://127.0.0.1/', 'https://www.dongguk.edu.evil.example/', 'https://www.dongguk.edu:8000/', 'https://user:pass@dorm.dongguk.edu/']:
            with self.assertRaises(ValueError):
                safe_url(url)


class MenuCacheTests(unittest.TestCase):
    def test_one_failed_source_preserves_its_last_success(self):
        scratch_root = Path(__file__).resolve().parents[1] / "data"
        scratch_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch_root) as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(scratch_root.resolve()))
            service = MenuService(directory)
            old_time = '2026-09-01T12:00:00+09:00'
            service.cache = {"version": 1, "generatedAt": '2000-01-01T00:00:00+09:00', "locations": {
                "business": {"status": "ready", "fetchedAt": old_time, "title": "저장된 메뉴", "images": [], "days": [], "attachments": []}
            }}

            def collect(location_id, now, web_root):
                if location_id == 'business':
                    raise TimeoutError()
                return {"status": "ready", "fetchedAt": now.isoformat(), "title": '</script><b>', "images": [], "days": [], "attachments": []}

            with patch('server.menu_service.collect_location', side_effect=collect):
                result = service.refresh(force=True)
            self.assertEqual(result["locations"]["business"]["status"], "stale")
            self.assertEqual(result["locations"]["business"]["fetchedAt"], old_time)
            self.assertEqual(result["locations"]["sangnok"]["status"], "ready")
            self.assertEqual(json.loads((Path(directory) / 'menus.json').read_text(encoding='utf-8')), result)
            self.assertNotIn('</script>', (Path(directory) / 'menu-cache.js').read_text(encoding='utf-8'))
            with patch('server.menu_service.collect_location') as mocked:
                self.assertIs(service.refresh(force=True), result)
                mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
