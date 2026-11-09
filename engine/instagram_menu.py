import base64
import json
import os
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

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