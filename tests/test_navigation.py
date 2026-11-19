import os
import unittest
from unittest.mock import patch


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
            'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json',
        }):
            import app
        cls.application = app

    def setUp(self):
        self.client = self.application.app.test_client()
        db_patch = patch.object(self.application, 'db', None)
        db_patch.start()
        self.addCleanup(db_patch.stop)

    def test_home_and_display_bookmarks_show_display_view(self):
        for path in ('/', '/display'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'id="compactView"', response.data)
                self.assertIn(b'id="headerTitle"', response.data)
                self.assertNotIn(b'class="location-icon"', response.data)
                self.assertIn(b'href="/" class="sidebar-link active"', response.data)
                for retired_link in (b'/manage', b'/analytics', b'/admin/analytics'):
                    self.assertNotIn(b'href="' + retired_link + b'"', response.data)

    def test_public_manage_page_is_removed(self):
        self.assertEqual(self.client.get('/manage').status_code, 404)

    def test_anonymous_analytics_page_and_data_are_not_public(self):
        self.assertEqual(self.client.get('/analytics').location, '/admin/analytics')
        response = self.client.get('/analytics', follow_redirects=True)
        self.assertEqual(response.request.path, '/admin/login')
        for path in ('/api/analytics', '/api/analytics/today-detail'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_admin_can_open_analytics_and_read_stats(self):
        with self.client.session_transaction() as session:
            session['admin'] = True
        self.assertIn(b'href="/admin/analytics"', self.client.get('/admin').data)
        response = self.client.get('/analytics', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request.path, '/admin/analytics')
        self.assertIn(b'<h1>Analytics</h1>', response.data)
        stats = self.client.get('/api/analytics?days=1')
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(len(stats.get_json()), 1)
        details = self.client.get('/api/analytics/today-detail')
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.get_json(), [])


if __name__ == '__main__':
    unittest.main()
