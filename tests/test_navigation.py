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
                self.assertIn(b'id="cardsView" class="view-container active"', response.data)
                self.assertIn(b'id="favFilterBtn"', response.data)
                self.assertIn(b'id="disp-btn-today"', response.data)
                self.assertIn(b'id="disp-btn-week"', response.data)
                for view in (b'cards', b'list', b'table', b'compact'):
                    self.assertNotIn(b'data-view="' + view + b'"', response.data)
                self.assertIn(b'id="headerTitle"', response.data)
                self.assertNotIn(b'class="location-icon"', response.data)
                self.assertIn(b'href="/tipsa" class="header-add-link"', response.data)
                self.assertIn(b'id="suggestRestaurantText">Tipsa om en restaurang</span>', response.data)
                self.assertIn(b'M5 12h14M12 5l7 7-7 7', response.data)
                self.assertIn(b'href="/" class="sidebar-link active"', response.data)
                for retired_link in (b'/manage', b'/analytics', b'/admin/analytics'):
                    self.assertNotIn(b'href="' + retired_link + b'"', response.data)

    def test_public_manage_page_is_removed(self):
        self.assertEqual(self.client.get('/manage').status_code, 404)

    def test_public_display_does_not_apply_removed_restaurant_preferences(self):
        page = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('restaurant_user_preferences', page)
        self.assertIn("onlyFavorites && !isFavorite(urlEntry.name)", page)
        self.assertIn("urlEntry.enabled === false", page)
        self.assertIn("allUrls.filter(u => u.enabled !== false)", page)
        self.assertIn("localStorage.getItem('lunch_favorites')", page)

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
        self.assertFalse(entry['read'])
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
        tip = {'id': 'tip-1', 'public_suggestion': True, 'name': 'Test Bistro', 'url': 'https://example.com'}
        with patch.object(self.application, 'load_staging', return_value=[
            tip,
            {'id': 'staging-1', 'name': 'Internal draft', 'url': 'https://example.org'},
        ]), patch.object(self.application, 'restaurant_tips_context', return_value={
            'tips': [tip], 'tips_unavailable': False,
        }), patch.object(self.application, 'scrape_url') as scrape:
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
        self.assertEqual(anonymous.get('/admin/restaurangtips/summary').status_code, 401)

    def test_submitted_tip_appears_in_admin_summary_without_reloading_dashboard(self):
        stored = {}
        firestore = Mock()
        collection = firestore.collection.return_value
        collection.document.return_value.create.side_effect = lambda entry: stored.update(entry)
        collection.document.return_value.delete.side_effect = stored.clear
        collection.document.return_value.update.side_effect = lambda entry: stored.update(entry)
        document = Mock(id='tip-1')
        document.to_dict.side_effect = lambda: dict(stored)
        document.exists = True
        collection.document.return_value.get.return_value = document
        collection.where.return_value.stream.side_effect = lambda **_: [document] if stored else []
        with self.client.session_transaction() as session:
            session['admin'] = True
        with patch.object(self.application, 'db', firestore), patch.object(
            self.application, 'FieldFilter', create=True
        ) as field_filter, patch.object(self.application, 'track_visit'):
            dashboard = self.client.get('/admin').get_data(as_text=True)
            self.assertIn('Inga nya restaurangtips', dashboard)
            self.assertNotIn('setInterval(refreshRestaurantTips', dashboard)
            self.assertIn("document.addEventListener('visibilitychange', refreshRestaurantTips)", dashboard)
            self.assertIn('if (document.hidden || tipsRefreshRunning) return;', dashboard)
            self.assertIn('if (event.persisted) refreshRestaurantTips();', dashboard)
            public = self.application.app.test_client()
            response = public.post('/tipsa', data={
                'name': '<b>New Bistro</b>', 'url': 'https://example.com/lunch',
            })
            self.assertEqual(response.status_code, 303)
            summary = self.client.get('/admin/restaurangtips/summary')
            self.assertEqual(summary.status_code, 200)
            self.assertIn('no-store', summary.headers['Cache-Control'])
            self.assertIn(b'1 nytt tips</strong> att granska', summary.data)
            self.assertIn(b'class="tip-new-badge"', summary.data)
            self.assertIn(b'&lt;b&gt;New Bistro&lt;/b&gt;', summary.data)
            self.assertIn(b'New Bistro', self.client.get('/admin').data)
            self.assertIn(b'Markera som l\xc3\xa4st', self.client.get('/admin/restaurangtips').data)
            field_filter.assert_called_with('public_suggestion', '==', True)
            collection.where.assert_called_with(filter=field_filter.return_value)
            self.assertEqual(self.client.post('/api/admin/restaurangtips/tip-1/read').status_code, 200)
            summary = self.client.get('/admin/restaurangtips/summary')
            self.assertNotIn(b'tip-new-badge', summary.data)
            self.assertIn('1 läst tips väntar på behandling.'.encode(), summary.data)
            inbox = self.client.get('/admin/restaurangtips').get_data(as_text=True)
            self.assertIn('Väntar på behandling (1)', inbox)
            self.assertNotIn('Markera som läst', inbox)
            self.assertIn('New Bistro', inbox)
            self.assertEqual(self.client.delete('/api/admin/staging/tip-1').status_code, 200)
            self.assertIn(b'Inga nya restaurangtips', self.client.get('/admin/restaurangtips/summary').data)

    def test_mark_tip_read_requires_admin_and_public_suggestion(self):
        path = '/api/admin/restaurangtips/tip-1/read'
        self.assertEqual(self.client.post(path).status_code, 401)
        with self.client.session_transaction() as session:
            session['admin'] = True
        self.assertEqual(self.client.post(path).status_code, 503)
        db = Mock()
        document = db.collection.return_value.document.return_value.get.return_value
        document.exists = True
        document.to_dict.return_value = {'public_suggestion': False}
        with patch.object(self.application, 'db', db):
            self.assertEqual(self.client.post(path).status_code, 404)
            db.collection.return_value.document.return_value.update.assert_not_called()
            document.exists = False
            self.assertEqual(self.client.post(path).status_code, 404)

    def test_legacy_unread_tips_appear_as_new(self):
        tip = {'id': 'tip-old', 'name': 'Old Bistro', 'url': 'https://example.org'}
        with self.client.session_transaction() as session:
            session['admin'] = True
        with patch.object(self.application, 'restaurant_tips_context', return_value={
            'tips': [tip], 'tips_unavailable': False,
        }):
            self.assertIn(b'1 nytt tips', self.client.get('/admin/restaurangtips/summary').data)
            self.assertIn(b'Markera som l\xc3\xa4st', self.client.get('/admin/restaurangtips').data)

    def test_new_and_pending_tips_are_separate_and_reduced_motion_is_supported(self):
        tips = [
            {'id': 'tip-new', 'name': 'New Bistro', 'url': 'https://example.org', 'read': False},
            {'id': 'tip-read', 'name': 'Pending Bistro', 'url': 'https://example.com', 'read': True},
        ]
        with self.client.session_transaction() as session:
            session['admin'] = True
        with patch.object(self.application, 'restaurant_tips_context', return_value={
            'tips': tips, 'tips_unavailable': False,
        }):
            dashboard = self.client.get('/admin').get_data(as_text=True)
            self.assertIn('1 nytt tips', dashboard)
            self.assertIn('1 läst tips väntar på behandling.', dashboard)
            self.assertIn('prefers-reduced-motion: reduce', dashboard)
            inbox = self.client.get('/admin/restaurangtips').get_data(as_text=True)
            new_section, pending_section = inbox.split('Väntar på behandling (1)', 1)
            self.assertIn('New Bistro', new_section)
            self.assertIn('Markera som läst', new_section)
            self.assertIn('Pending Bistro', pending_section)
            self.assertNotIn('Markera som läst', pending_section)

    def test_firestore_read_failure_is_reported(self):
        class FirestoreError(Exception):
            pass

        with self.client.session_transaction() as session:
            session['admin'] = True
        db = Mock()
        db.collection.return_value.document.return_value.get.side_effect = FirestoreError()
        with patch.object(self.application, 'db', db), patch.object(
            self.application, 'GoogleAPICallError', FirestoreError, create=True
        ), self.assertLogs(self.application.app.logger, level='ERROR'):
            response = self.client.post('/api/admin/restaurangtips/tip-1/read')
        self.assertEqual(response.status_code, 503)
        self.assertIn('kunde inte markeras', response.get_json()['error'])

    def test_unavailable_inbox_is_not_reported_as_empty(self):
        with self.client.session_transaction() as session:
            session['admin'] = True
        summary = self.client.get('/admin/restaurangtips/summary')
        self.assertEqual(summary.status_code, 503)
        self.assertIn(b'Restaurangtips kunde inte', summary.data)
        self.assertNotIn(b'Inga nya restaurangtips', summary.data)

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
        dashboard = self.client.get('/admin').data
        analytics_section = dashboard.split(b'aria-labelledby="analyticsTitle">', 1)[1].split(b'</section>', 1)[0]
        header = analytics_section.split(b'<div class="analytics-card-header">', 1)[1].split(b'</div>', 1)[0]
        self.assertIn(b'id="analyticsTitle"', header)
        self.assertIn(b'href="/admin/analytics"', header)
        self.assertEqual(analytics_section.count(b'href="/admin/analytics"'), 1)
        self.assertLess(dashboard.index(b'Analytics / Bes'), dashboard.index(b'id="sys-firebase"'))
        self.assertLess(dashboard.index(b'id="chartBars"'), dashboard.index(b'id="sys-firebase"'))
        self.assertIn(b'renderChart(await fetchDailyVisits(7))', dashboard)
        self.assertNotIn(b'id="todayBody"', dashboard)
        response = self.client.get('/analytics', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request.path, '/admin/analytics')
        self.assertIn(b'<h1>Analytics</h1>', response.data)
        for element_id in (b'chartBars', b'tableBody', b'todayBody'):
            self.assertIn(b'id="' + element_id + b'"', response.data)
        self.assertIn(b'loadAnalytics(30, this)', response.data)
        stats = self.client.get('/api/analytics?days=1')
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(len(stats.get_json()), 1)
        details = self.client.get('/api/analytics/today-detail')
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.get_json(), [])


if __name__ == '__main__':
    unittest.main()
