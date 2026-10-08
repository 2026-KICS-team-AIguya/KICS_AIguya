import unittest
from pathlib import Path
from unittest.mock import patch

from server.menu_cloud import cloud_image_descriptor, official_image_url
from server.menu_service import MenuService


class CloudMenuTests(unittest.TestCase):
    def test_image_transport_is_limited_to_menu_upload_folders(self):
        allowed = 'https://dorm.dongguk.edu/cmmn/fileView?path=/ckeditor//food&physical=1790830820464.png&contentType=image'
        self.assertEqual(official_image_url(allowed), allowed)
        self.assertTrue(cloud_image_descriptor(allowed, None)['path'].startswith('/api/menu-image?source='))
        for url in [
            'https://127.0.0.1/cmmn/fileView?path=/ckeditor//food&physical=a.png&contentType=image',
            allowed.replace('/ckeditor//food', '/private'),
            allowed.replace('1790830820464.png', '../private.png'),
            allowed.replace('contentType=image', 'contentType=text'),
            allowed + '&physical=other.png',
        ]:
            with self.assertRaises(ValueError):
                official_image_url(url)

    def test_refresh_with_read_only_filesystem_does_not_write(self):
        service = MenuService(persist=False)
        service.cache = {'version': 1, 'generatedAt': None, 'locations': {}}

        def collect(location_id, now, web_root):
            return {'status': 'ready', 'fetchedAt': now.isoformat(), 'images': [], 'days': [], 'attachments': []}

        with patch('server.menu_service.collect_location', side_effect=collect), \
                patch.object(Path, 'mkdir', side_effect=AssertionError('Filesystem write')), \
                patch.object(Path, 'write_text', side_effect=AssertionError('Filesystem write')):
            result = service.refresh(force=True)
        self.assertEqual(len(result['locations']), 3)
        self.assertTrue(all(menu['status'] == 'ready' for menu in result['locations'].values()))


if __name__ == '__main__':
    unittest.main()
