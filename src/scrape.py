import datetime
import json
import logging
from html import unescape
from pathlib import Path
from typing import TypedDict

import requests
from bs4 import BeautifulSoup
from requests.models import Response

NUM_TIMEOUT_ATTEMPTS = 3
TIMEOUT_SECONDS = 5

logger = logging.getLogger(__name__)


class TimeoutRetryError(Exception):
    pass


class Sibling(TypedDict):
    date: str
    start_time: str
    title: str


def scrape(
    schedule_filepath: Path,
):
    # Parse and save simple schedule.
    # """
    schedule = scrape_schedule()
    # """

    # Get and save events and venues.
    # """
    scrape_events(schedule)

    # Get and save venues (opening hours).
    scrape_venues(schedule)
    # """

    with open(schedule_filepath, 'w', encoding='utf-8') as file:
        json.dump(schedule, file, ensure_ascii=False, indent=4)
    logger.info('Schedule saved.')



def scrape_schedule() -> dict:
    logger.info('Scraping schedule')

    # Get page.
    url = 'https://www.medeltidsveckan.se/programme/'
    response = _get_request(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Get weekdays in correct locale.
    weekdays = tuple(button.text for button in soup.select('#day-list button'))

    # Get days.
    days = []
    num_venues = 0
    num_events = 0
    day_elements = soup.select('.day')
    for day_index, day_element in enumerate(day_elements):
        date_string = day_element.get('id').removeprefix('date-')
        day = {
            'date': date_string,
            'weekday': weekdays[day_index],
            'venues': [],
            'time_slots': [],
        }
        logger.debug(f'Scraping {weekdays[day_index]} {date_string}')

        # Get venues (opening hours).
        if hours_element := day_element.select_one(f'#hours-{date_string}'):
            for hour_element in hours_element.select('a'):
                id_ = int(hour_element['data-pid'])
                logger.debug(f'Scraping venue {id_} from schedule')
                time_element, title_element = hour_element.select('div')
                start_time, end_time = time_element.string.split('-')
                day['venues'].append(
                    {
                        'id': id_,
                        'title': title_element.string,
                        'start_time': start_time,
                        'end_time': end_time,
                    }
                )
                num_venues += 1

        # Get time slots.
        time_views = day_element.select('.time-view')
        for time_view in time_views:
            time_slot = {
                'time': time_view.select_one('.time-header h4').string,
                'events': [],
            }
            # Get events.
            for article in time_view.select('article'):
                event = {}
                id_ = int(article['data-pid'])
                logger.debug(f'Scraping event {id_} from schedule')
                title = unescape(article.select_one('strong').string)
                start_time = article.select_one('span').string
                event['id'] = id_
                event['title'] = title
                event['start_time'] = start_time
                category = next(article.select_one('.card-footer').stripped_strings, 'Övrigt')
                # The category is missing if the link text is caught instead.
                if category == 'Köp biljett':
                    category = 'Övrigt'
                event['category'] = category
                time_slot['events'].append(event)
                num_events += 1
            day['time_slots'].append(time_slot)

        days.append(day)
    logger.info(f'Schedule contains {num_events} events')
    return {
        'num_venues': num_venues,
        'num_events': num_events,
        'days': days,
    }


def scrape_events(schedule: dict):
    logger.info('Scraping events')

    num_events = schedule['num_events']
    num_scraped = 0
    for day in schedule['days']:
        for time_slot in day['time_slots']:
            for event in time_slot['events']:
                try:
                    _scrape_occasion(event)
                    if ticket_id := event.get('ticket_id'):
                        _scrape_ticket_price_range(event, ticket_id)
                    for sibling in event.get('siblings', []):
                        sibling['id'] = _find_event_sibling_id(
                            event=event, sibling=sibling, schedule=schedule
                        )

                # Skip failed scrapes.
                except TimeoutRetryError as exception:
                    logger.error(f'Failed to scrape event {event['id']}: {exception}')

                num_scraped += 1
                if (num_scraped + 1) % 20 == 0 or num_scraped == num_events - 1:
                    logger.info(f'{num_scraped + 1}/{num_events} events scraped')


def scrape_venues(schedule: dict):
    logger.info('Scraping venues')

    num_venues = schedule['num_venues']
    num_scraped = 0
    for day in schedule['days']:
        for venue in day['venues']:
            try:
                _scrape_occasion(venue)
                for sibling in venue.get('siblings', []):
                    sibling['id'] = _find_venue_sibling_id(
                        venue=venue, sibling=sibling, schedule=schedule
                    )
            # Skip failed scrapes.
            except TimeoutRetryError as exception:
                logger.error(f'Failed to scrape venue {venue['id']}: {exception}')

            num_scraped += 1
            if (num_scraped + 1) % 20 == 0 or num_scraped == num_venues - 1:
                logger.info(f'{num_scraped + 1}/{num_venues} venues scraped')


def _get_request(url: str, *, params=None) -> Response:
    """Returns response of GET request, unless multiple attempts time out."""

    params = params if not None else {}

    for i in range(NUM_TIMEOUT_ATTEMPTS):
        try:
            response = requests.get(url, timeout=TIMEOUT_SECONDS, params=params)
            response.raise_for_status()
            return response
        except requests.exceptions.ReadTimeout:
            logger.debug(f'GET request {i + 1}/{NUM_TIMEOUT_ATTEMPTS} failed for {url}')
    raise TimeoutRetryError(f'Too many timeouts for GET request to {url}')


def _scrape_occasion(occasion: dict) -> dict:
    logger.debug(f'Scraping details for occasion {occasion['id']}')
    # Get json.
    url = 'https://www.medeltidsveckan.se/'
    response = _get_request(
        url,
        params={
            'action': 'fetch-programme-item',
            'pid': occasion['id'],
        },
    )
    response.raise_for_status()
    details = response.json()

    # Parse details.
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
                    'start_time': unescape(sibling['time']),
                    'title': unescape(sibling['title']),
                }
            )
    occasion['date'] = details['sidebar']['date']
    start, end = details['sidebar']['time'].split(' - ')
    occasion['start_time'] = unescape(start)
    occasion['end_time'] = unescape(end)
    occasion['location'] = unescape(details['sidebar']['venue'])
    if ticket_url := details['sidebar']['ticket_link']:
        ticket_id = int(ticket_url.split('/')[-1])
        occasion['ticket_id'] = ticket_id


def _scrape_ticket_price_range(event: dict, ticket_id: int) -> tuple[int, int] | None:
    logger.debug(f'Scraping ticket {ticket_id}')

    # Get json.
    url = f'https://www.nortic.se/api/json/show/{ticket_id}'
    response = _get_request(url)
    response.raise_for_status()
    data = response.json()

    # Get price range.
    events = data['events']
    if len(events) == 0:
        logger.warning(f'Found no events for ticket {ticket_id}')
        return None
    show = events[0]['shows'][0]
    min_price = int(float(show['minPrice']))
    max_price = int(float(show['maxPrice']))

    if min_price == max_price:
        event['price'] = min_price
    else:
        event['min_price'] = min_price
        event['max_price'] = max_price


def _find_event_sibling_id(event: dict, sibling: dict, schedule: dict):

    day = next(day for day in schedule['days'] if day['date'] == sibling['date'])

    start_hour, start_minute = sibling['start_time'].split(':')
    earliest_half_hour = int(start_minute) // 30 * 30
    sibling_time_slot = f'{start_hour}:{earliest_half_hour:02d}'
    time_slot = next(time_slot for time_slot in day['time_slots'] if time_slot['time'] == sibling_time_slot)

    sibling = next(event for event in time_slot['events'] if event['title'] == sibling['title'])
    return sibling['id']


def _find_venue_sibling_id(venue: dict, sibling: dict, schedule: dict):

    day = next(day for day in schedule['days'] if day['date'] == sibling['date'])

    sibling = next(
        venue for venue in day['venues']
        if venue['title'] == sibling['title'] and venue['start_time'] == sibling['start_time']
    )
    return sibling['id']
