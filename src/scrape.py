import datetime
import logging
from html import unescape
from typing import Literal

import requests
from bs4 import BeautifulSoup
from requests.models import Response

from src.log import *

NUM_TIMEOUT_ATTEMPTS = 3
TIMEOUT_SECONDS = 5

logger = logging.getLogger(__name__)


class TimeoutRetryError(Exception):
    pass


def scrape_schedule(*, verbose=False) -> dict:
    days = []
    num_events = 0

    # Get page.
    url = 'https://www.medeltidsveckan.se/programme/'
    logger.info(f'Getting schedule from {url}')
    response = _get_request(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Get weekdays in correct locale.
    weekdays = tuple(button.text for button in soup.select('#day-list button'))

    # Get days.
    day_elements = soup.select('.day')
    for day_index, day_element in enumerate(day_elements):
        date_string = day_element.get('id').removeprefix('date-')
        day = {
            'date': date_string,
            'venues': [],
            'events': [],
        }
        if verbose:
            weekday = weekdays[day_index]
            print(weekday, date_string)

        # Get venues (opening hours).
        if hours_element := day_element.select_one(f'#hours-{date_string}'):
            for hour_element in hours_element.select('a'):
                time_element, title_element = hour_element.select('div')
                start_time, end_time = time_element.string.split('-')
                day['venues'].append(
                    {
                        'id': int(hour_element['data-pid']),
                        'title': title_element.string,
                        'start_time': start_time,
                        'end_time': end_time,
                    }
                )

        # Get time slots.
        time_views = day_element.select('.time-view')
        for time_view in time_views:
            if verbose:
                time_slot = time_view.select_one('h4').string
                print('-', time_slot)

            # Get events.
            for article in time_view.select('article'):
                event = {}
                id = int(article['data-pid'])
                event['id'] = id
                event['title'] = unescape(article.select_one('strong').string)
                event['start_time'] = article.select_one('span').string
                if footer := article.select_one('.card-footer').string:
                    event['category'] = footer.strip()
                if verbose:
                    print('  -', event['id'], event['title'])
                day['events'].append(event)
                num_events += 1

        days.append(day)
    logger.info(f'Schedule contains {num_events} events')
    return days


def scrape_events(schedule: dict):
    return _scrape_occasions(schedule, 'event')


def scrape_venues(schedule: dict):
    return _scrape_occasions(schedule, 'venue')


def scrape_ticket_price_range(ticket_id: int, *, verbose=False) -> tuple[int, int] | None:
    # Get json.
    url = f'https://www.nortic.se/api/json/show/{ticket_id}'
    response = _get_request(url)
    response.raise_for_status()
    data = response.json()

    # Get price range.
    events = data['events']
    if len(events) == 0:
        return None
    show = events[0]['shows'][0]
    min_price = int(float(show['minPrice']))
    max_price = int(float(show['maxPrice']))
    if verbose:
        print(f'- {ticket_id}: ', end='')
        if min_price == max_price:
            print(f'{min_price:4d}')
        else:
            print(f'{min_price:4d} - {max_price:4d}')

    return (min_price, max_price)


def _get_request(url: str, *, params=None) -> Response:
    """Returns response of GET request, unless multiple attempts time out."""

    params = params if not None else {}

    for _ in range(NUM_TIMEOUT_ATTEMPTS):
        try:
            response = requests.get(url, timeout=TIMEOUT_SECONDS, params=params)
            response.raise_for_status()
            return response
        except requests.exceptions.ReadTimeout:
            pass
    raise TimeoutRetryError(f'Too many timeouts for GET request to {url}')


def _scrape_occasion(id_: int, *, verbose=False) -> dict:
    # Get json.
    url = 'https://www.medeltidsveckan.se/'
    response = _get_request(
        url,
        params={
            'action': 'fetch-programme-item',
            'pid': id_,
        },
    )
    response.raise_for_status()
    details = response.json()

    # Parse details.
    occasion = {
        'id': id_,
    }
    if image_url := details.get('image'):
        occasion['image_url'] = image_url
    if item_owner := details['header']['item_owner']:
        occasion['owner'] = unescape(item_owner)
    occasion['title'] = unescape(details['header']['title'])
    occasion['html_escaped_description'] = details['content']['description']
    if siblings := details['content']['siblings']:
        occasion['siblings'] = []
        for sibling in siblings.values():
            timestamp = int(sibling['timestamp'])
            date = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).date()
            occasion['siblings'].append(
                {
                    'date': str(date),
                    'weekday': unescape(sibling['day']),
                    'start_time': unescape(sibling['time']),
                    'title': unescape(sibling['title']),
                }
            )
    occasion['weekday'] = details['sidebar']['dayName']
    occasion['date'] = details['sidebar']['date']
    start, end = details['sidebar']['time'].split(' - ')
    occasion['start_time'] = unescape(start)
    occasion['end_time'] = unescape(end)
    occasion['location'] = unescape(details['sidebar']['venue'])
    if ticket_url := details['sidebar']['ticket_link']:
        ticket_id = int(ticket_url.split('/')[-1])
        occasion['ticket_id'] = ticket_id
    if verbose:
        print('-', id_, occasion['weekday'], occasion['start_time'], occasion['title'])
    return occasion


def _scrape_occasions(schedule: dict, type_: Literal['event', 'venue']):
    log_info_and_print(f'Scraping {type_}s')

    ids: list[int] = []
    for day in schedule:
        for occasion in day[f'{type_}s']:
            ids.append(occasion['id'])

    occasions = []
    for i, id_ in enumerate(ids):
        print(f'Getting {type_} {i + 1}/{len(ids)}: {id_}')
        try:
            occasion = _scrape_occasion(id_)
            occasions.append(occasion)
        # Skip failed scrapes.
        except TimeoutRetryError as exception:
            log_error_and_print(f'Failed to get {type_} {id_}: {exception}')
            continue

    log_info_and_print(f'Scraped {len(occasions)}/{len(ids)} {type_}s')
    return occasions


def main():
    """Scrapes schedule, some events and a ticket, and only prints the result."""
    logging.basicConfig(
        filename=f'{__file__}.log',
        level=logging.INFO,
        style='{',
        format='{asctime}:{levelname}:{name}:{filename}:{lineno}:{message}',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    # Scrape schedule
    print('The schedule:')
    schedule = scrape_schedule(verbose=True)

    # Scrape events until a ticket with a price is found
    has_scraped = False
    print('\nSome events:')
    for day in schedule:
        for event in day['events']:
            event_id = event['id']
            event = _scrape_occasion(event_id, verbose=True)
            if ticket_id := event.get('ticket_id'):
                print('\nA ticket:')
                scrape_ticket_price_range(ticket_id, verbose=True)
                has_scraped = True
                break
        if has_scraped:
            break


if __name__ == '__main__':
    main()
