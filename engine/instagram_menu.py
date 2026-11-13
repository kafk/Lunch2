import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import ValidationError

from .fetcher import create_session
from .models import WeeklyMenuResult
from .normalizer import normalize_text_to_days, format_day_menus_to_text
from .openai_menu import SourcedMenu
from .validator import validate_menu_result, menu_freshness_error


def current_week_menu(menu, now):
    return not menu_freshness_error(menu, now)


def _post_records(value):
    if isinstance(value, dict):
        if 'shortcode' in value or ('code' in value and 'image_versions2' in value):
            yield value
        for child in value.values():
            yield from _post_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _post_records(child)
    elif isinstance(value, str) and value.startswith(('{', '[')):
        try:
            yield from _post_records(json.loads(value))
        except ValueError:
            pass


def _caption(post):
    caption = post.get('caption') or {}
    if isinstance(caption, str):
        return caption
    edges = post.get('edge_media_to_caption', {}).get('edges', [])
    return caption.get('text', '') or '\n'.join(
        edge.get('node', {}).get('text', '') for edge in edges
    )


def _validated_menu(text, url, name, now, source):
    days = normalize_text_to_days(text)
    if len(days) < 2:
        return None
    result = WeeklyMenuResult(
        restaurant_id='backside', name=name, url=url, success=True,
        source=source, raw_text=text, days=days,
        formatted_menu=format_day_menus_to_text(days),
        scraped_at=now.strftime('%Y-%m-%d %H:%M')
    )
    if validate_menu_result(result)[0]:
        return result.to_dict()
    return None


def _image_menu(image_url, post_url, session, now, reasons):
    key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not key:
        reasons.append('Instagram image OCR unavailable: no Gemini key')
        return ''
    image = session.get(image_url, timeout=12)
    image.raise_for_status()
    mime = image.headers.get('Content-Type', '').split(';')[0]
    if mime not in ('image/jpeg', 'image/png', 'image/webp') or len(image.content) > 8_000_000:
        reasons.append('Instagram menu image rejected: unsupported or too large')
        return ''
    year, week = now.isocalendar()[:2]
    response = session.post(
        'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent',
        headers={'x-goog-api-key': key.strip()}, timeout=40,
        json={
            'contents': [{'parts': [
                {'text': f'Copy only the lunch dishes visible in this image. '
                         f'The required ISO year/week is {year}/{week}. '
                         'Read the menu week from the image; do not assume it. '
                         'If missing or different, return days: []. '
                         'Use lowercase English weekday names, preserve Swedish dishes, '
                         f'and set source_url to {post_url}.'},
                {'inlineData': {'mimeType': mime, 'data': base64.b64encode(image.content).decode('ascii')}}
            ]}],
            'generationConfig': {'responseMimeType': 'application/json',
                                 'responseJsonSchema': SourcedMenu.model_json_schema()}
        }
    )
    if response.status_code != 200:
        reasons.append(f'Instagram OCR HTTP {response.status_code}')
        return ''
    parts = response.json()['candidates'][0]['content']['parts']
    menu = SourcedMenu.model_validate_json(''.join(part.get('text', '') for part in parts))
    if (menu.year, menu.week) != (year, week) or menu.source_url != post_url:
        reasons.append('Instagram OCR rejected: wrong menu week or source')
        return ''
    if len(menu.days) < 2 or len({day.day for day in menu.days}) != len(menu.days):
        reasons.append('Instagram OCR rejected: incomplete menu')
        return ''
    labels = dict(zip(
        ('monday', 'tuesday', 'wednesday', 'thursday', 'friday'),
        ('M\u00e5ndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag')
    ))
    return '\n\n'.join(labels[day.day] + '\n' + '\n'.join(day.dishes) for day in menu.days)


def fetch_apify_menu(url, name, now, session=None, reasons=None):
    reasons = reasons if reasons is not None else []
    token = os.environ.get('APIFY_API_TOKEN', '').strip()
    task = os.environ.get('APIFY_BACKSIDE_TASK_ID', '').strip()
    if not token and not task:
        return None
    if not token or not task:
        reasons.append('Apify: APIFY_API_TOKEN and APIFY_BACKSIDE_TASK_ID are both required')
        return None
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:~[A-Za-z0-9_-]+)?', task):
        reasons.append('Apify: invalid task ID')
        return None
    session = session or create_session()
    try:
        response = session.get(
            f'https://api.apify.com/v2/actor-tasks/{task}/runs/last/dataset/items',
            headers={'Authorization': f'Bearer {token}'},
            params={'status': 'SUCCEEDED', 'format': 'json', 'clean': 'true', 'limit': 5},
            timeout=12, allow_redirects=False,
        )
        if response.status_code != 200:
            reasons.append(f'Apify dataset HTTP {response.status_code}')
            return None
        posts = response.json()
        if not isinstance(posts, list) or any(not isinstance(post, dict) for post in posts):
            reasons.append('Apify: invalid dataset response')
            return None
        current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        monday = (current - timedelta(days=current.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Restaurants often publish Monday's menu on the preceding Sunday.
        earliest = monday - timedelta(days=1)
        username = urlparse(url).path.strip('/').lower()
        candidates = []
        for post in posts[:5]:
            if post.get('ownerUsername', '').lower() != username:
                continue
            try:
                published = datetime.fromisoformat(post.get('timestamp', '').replace('Z', '+00:00'))
            except (ValueError, TypeError, AttributeError):
                reasons.append('Apify: invalid post timestamp')
                continue
            if not published.tzinfo or not earliest <= published <= current:
                continue
            caption = _caption(post)
            weeks = re.findall(r'\b(?:vecka|v\.?)[ \t]*(\d{1,2})\b', caption, re.I)
            if weeks and any(int(week) != now.isocalendar().week for week in weeks):
                continue
            candidates.append((published, post))
        attempts = 0
        seen_images = set()
        for _, post in sorted(candidates, key=lambda item: item[0], reverse=True):
            code = post.get('shortCode', '')
            if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', code):
                reasons.append('Apify: invalid post shortcode')
                continue
            post_url = f'https://www.instagram.com/p/{code}/'
            images = [post.get('displayUrl')]
            images.extend(post.get('images') or [])
            images.extend(
                child.get('displayUrl') for child in (post.get('childPosts') or [])
                if isinstance(child, dict)
            )
            for image_url in images:
                if not isinstance(image_url, str) or image_url in seen_images:
                    continue
                parsed = urlparse(image_url)
                host = parsed.hostname or ''
                if (parsed.scheme != 'https' or parsed.username or parsed.password
                        or not host.endswith(('.cdninstagram.com', '.fbcdn.net'))):
                    reasons.append('Apify: untrusted menu image URL')
                    continue
                seen_images.add(image_url)
                if attempts >= 2:
                    break
                attempts += 1
                text = _image_menu(image_url, post_url, session, now, reasons)
                result = _validated_menu(text, url, name, now, 'Apify Instagram image OCR')
                if result:
                    result.update(menu_source_url=post_url, fallback_used=False,
                                  menu_year=now.isocalendar().year,
                                  menu_week=now.isocalendar().week)
                    return result
        reasons.append('Apify: no verified current-week menu')
    except (requests.RequestException, ValidationError, ValueError, KeyError, TypeError) as error:
        reasons.append(f'Apify fetch failed: {type(error).__name__}')
    return None


def fetch_instagram_menu(url, name, now, session=None, reasons=None):
    reasons = reasons if reasons is not None else []
    session = session or create_session()
    try:
        response = session.get(url, timeout=12)
        response.raise_for_status()
        if '/accounts/' in response.url:
            reasons.append('Instagram requires login')
            return None
        soup = BeautifulSoup(response.text, 'lxml')
        posts = []
        for script in soup.find_all('script', type='application/json'):
            try:
                posts.extend(_post_records(json.loads(script.string or script.get_text())))
            except (ValueError, TypeError):
                continue
        seen = set()
        for post in posts:
            code = post.get('shortcode') or post.get('code')
            if code in seen:
                continue
            seen.add(code)
            if len(seen) > 2:
                break
            post_url = urljoin(url, '/p/' + code + '/')
            text = _caption(post)
            weeks = re.findall(r'\b(?:vecka|v\.?)[ \t]*(\d{1,2})\b', text, re.I)
            if weeks and any(int(week) != now.isocalendar().week for week in weeks):
                continue
            timestamp = post.get('taken_at_timestamp') or post.get('taken_at')
            if not timestamp or now.fromtimestamp(timestamp, now.tzinfo).isocalendar()[:2] != now.isocalendar()[:2]:
                continue
            result = _validated_menu(text, url, name, now, 'Instagram caption') if weeks else None
            if not result:
                images = post.get('image_versions2', {}).get('candidates', [])
                image_url = post.get('display_url') or (images[0].get('url') if images else None)
                if not image_url or urlparse(image_url).scheme != 'https':
                    continue
                text = _image_menu(image_url, post_url, session, now, reasons)
                result = _validated_menu(text, url, name, now, 'Instagram image OCR')
            if result:
                result['menu_source_url'] = post_url
                result['fallback_used'] = False
                return result
        reasons.append('Instagram: no accessible current-week menu posts')
    except Exception as error:
        reasons.append(f'Instagram fetch failed: {type(error).__name__}')
    return None