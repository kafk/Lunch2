import os
import unittest
from unittest.mock import Mock, patch


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
                self.assertIn(b'href="/tipsa" class="header-add-link"', response.data)
                self.assertIn(b'href="/" class="sidebar-link active"', response.data)
                for retired_link in (b'/manage', b'/analytics', b'/admin/analytics'):
                    self.assertNotIn(b'href="' + retired_link + b'"', response.data)

    def test_public_manage_page_is_removed(self):
        self.assertEqual(self.client.get('/manage').status_code, 404)

    def test_suggestion_is_saved_for_review_without_scraping_or_publishing(self):
        firestore = Mock()
        with patch.object(self.application, 'db', firestore), patch.object(
            self.application, 'scrape_url'
        ) as scrape, patch.object(self.application, 'load_urls') as live:
            response = self.client.post('/tipsa?lang=en', data={
                'name': ' Test Bistro ', 'url': 'https://example.com/lunch#today',
            }, follow_redirects=True)
        self.assertIn(b'Thanks for your suggestion', response.data)
        self.assertEqual(response.history[0].status_code, 303)
        firestore.collection.assert_called_once_with('restaurants_staging')
        doc = firestore.collection.return_value.document
        self.assertRegex(doc.call_args.args[0], r'^tip-[a-f0-9]{64}$')
        entry = doc.return_value.create.call_args.args[0]
        self.assertEqual(entry['name'], 'Test Bistro')
        self.assertEqual(entry['url'], 'https://example.com/lunch')
        self.assertIsNone(entry['source_index'])
        self.assertTrue(entry['public_suggestion'])
        scrape.assert_not_called()
        live.assert_not_called()

    def test_suggestion_form_validates_links_and_reports_unavailable_storage(self):
        form = self.client.get('/tipsa?lang=en')
        self.assertIn(b'Suggest a restaurant', form.data)
        self.assertIn(b'id="suggestUrl"', form.data)
        with patch.object(self.application, 'db', Mock()) as firestore:
            for url in ('file:///menu', 'https://127.0.0.1/menu', 'https://a@b.com/menu'):
                with self.subTest(url=url):
                    response = self.client.post('/tipsa', data={'name': 'Bistro', 'url': url})
                    self.assertEqual(response.status_code, 400)
            firestore.collection.assert_not_called()
        response = self.client.post('/tipsa?lang=en', data={'name': 'Bistro', 'url': 'https://example.com'})
        self.assertEqual(response.status_code, 503)
        self.assertIn(b'could not be saved', response.data)

    def test_suggestion_storage_deduplicates_and_reports_firestore_errors(self):
        class FirestoreError(Exception):
            pass

        class DuplicateError(FirestoreError):
            pass

        firestore = Mock()
        create = firestore.collection.return_value.document.return_value.create
        create.side_effect = [DuplicateError(), FirestoreError()]
        with patch.object(self.application, 'db', firestore), patch.object(
            self.application, 'AlreadyExists', DuplicateError, create=True
        ), patch.object(self.application, 'GoogleAPICallError', FirestoreError, create=True):
            payload = {'name': 'Bistro', 'url': 'https://example.com'}
            self.assertEqual(self.client.post('/tipsa', data=payload).status_code, 303)
            with self.assertLogs(self.application.app.logger, level='ERROR'):
                self.assertEqual(self.client.post('/tipsa', data=payload).status_code, 503)

    def test_public_suggestions_are_not_available_to_staging_scraper(self):
        for method, suffix in (('GET', ''), ('POST', ''), ('DELETE', '/tip-1'),
                               ('POST', '/tip-1/test'), ('POST', '/tip-1/promote')):
            with self.subTest(method=method, suffix=suffix):
                response = self.client.open('/api/admin/staging' + suffix, method=method)
                self.assertEqual(response.status_code, 401)
        with self.client.session_transaction() as session:
            session['admin'] = True
        with patch.object(self.application, 'load_staging', return_value=[
            {'id': 'tip-1', 'public_suggestion': True, 'name': 'Test Bistro', 'url': 'https://example.com'},
            {'id': 'staging-1', 'name': 'Internal draft', 'url': 'https://example.org'},
        ]), patch.object(self.application, 'scrape_url') as scrape:
            self.assertEqual(self.client.get('/api/admin/staging').get_json()[0]['id'], 'tip-1')
            self.assertEqual(self.client.post('/api/admin/staging/tip-1/test').status_code, 400)
            self.assertIn(b'href="/admin/restaurangtips"', self.client.get('/admin').data)
            page = self.client.get('/admin/restaurangtips')
            self.assertEqual(page.status_code, 200)
            self.assertIn(b'Test Bistro', page.data)
            self.assertIn(b'data-delete-url="/api/admin/staging/tip-1"', page.data)
            self.assertNotIn(b'Internal draft', page.data)
        scrape.assert_not_called()
        anonymous = self.application.app.test_client()
        self.assertEqual(anonymous.get('/admin/restaurangtips').location, '/admin/login')

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
