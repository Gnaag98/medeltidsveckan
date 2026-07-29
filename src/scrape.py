import datetime
import json
import logging
from collections.abc import Callable
from html import unescape
from pathlib import Path
from typing import Literal, TypedDict

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
    events_filepath: Path,
    venues_filepath: Path,
):
    # Parse and save simple schedule.
    # """
    schedule = scrape_schedule()
    with open(schedule_filepath, 'w', encoding='utf-8') as file:
        json.dump(schedule, file, ensure_ascii=False, indent=4)
    logger.info('Schedule saved.')
    # """

    # Get and save events and venues.
    # """
    with open(schedule_filepath, 'r') as file:
        schedule = json.load(file)

    events = scrape_events(schedule)
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    logger.info('Events saved')

    # Get and save venues (opening hours).
    venues = scrape_venues(schedule)
    with open(venues_filepath, 'w', encoding='utf-8') as file:
        json.dump(venues, file, ensure_ascii=False, indent=4)
    logger.info('Venues saved')
    # """

    # Update saved events with ticket prices.
    # """
    add_ticket_prices(events_filepath)
    # """

    # Update saved events and venues with sibling IDs.
    # """
    with open(schedule_filepath, 'r', encoding='utf-8') as file:
        schedule = json.load(file)

    # Update events.
    logger.info('Updating saved events with sibling IDs')
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    add_sibling_ids(events, schedule, _find_event_sibling_id)
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    logger.info('Updated saved events with sibling IDs')

    # Update venues.
    logger.info('Updating saved venues with sibling IDs')
    with open(venues_filepath, 'r', encoding='utf-8') as file:
        venues = json.load(file)
        add_sibling_ids(venues, schedule, _find_venue_sibling_id)
    with open(venues_filepath, 'w', encoding='utf-8') as file:
        json.dump(venues, file, ensure_ascii=False, indent=4)
    logger.info('Updated saved venues with sibling IDs')
    # """


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
    num_events = 0
    day_elements = soup.select('.day')
    for day_index, day_element in enumerate(day_elements):
        date_string = day_element.get('id').removeprefix('date-')
        day = {
            'date': date_string,
            'venues': [],
            'events': [],
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

        # Get events.
        time_views = day_element.select('.time-view')
        for time_view in time_views:
            for article in time_view.select('article'):
                event = {}
                id_ = int(article['data-pid'])
                logger.debug(f'Scraping event {id_} from schedule')
                title = unescape(article.select_one('strong').string)
                start_time = article.select_one('span').string
                event['id'] = id_
                event['title'] = title
                event['start_time'] = start_time
                if footer := article.select_one('.card-footer').string:
                    event['category'] = footer.strip()
                day['events'].append(event)
                num_events += 1

        days.append(day)
    logger.info(f'Schedule contains {num_events} events')
    return days


def scrape_events(schedule: dict):
    logger.info('Scraping events')
    return _scrape_occasions(schedule, 'event')


def scrape_venues(schedule: dict):
    logger.info('Scraping venues')
    return _scrape_occasions(schedule, 'venue')


def scrape_ticket_price_range(ticket_id: int) -> tuple[int, int] | None:
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

    return (min_price, max_price)


def add_ticket_prices(events_filepath: Path):
    logger.info('Updating saved events with ticket prices')
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    for i, event in enumerate(events):
        if ticket_id := event.get('ticket_id'):
            logger.debug(f'Adding ticket price to event {event["id"]} ({i + 1}/{len(events)})')
            if price_range := scrape_ticket_price_range(ticket_id):
                min_price = price_range[0]
                max_price = price_range[1]
                if min_price == max_price:
                    event['price'] = max_price
                else:
                    event['min_price'] = min_price
                    event['max_price'] = max_price

        if (i + 1) % 20 == 0 or i == len(events) - 1:
            logger.info(f'{i + 1}/{len(events)} tickets scraped')

    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    logger.info('Updated saved events with ticket prices')


def add_sibling_ids(occasions: dict, schedule: dict, find_occasion_sibling_id: Callable):
    for occasion in occasions:
        if siblings := occasion.get('siblings'):
            for sibling in siblings:
                sibling_id = find_occasion_sibling_id(sibling, schedule)
                sibling['sibling_id'] = sibling_id
                logger.debug(f'Added sibling id {sibling_id} to {occasion["id"]}')


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


def _scrape_occasion(id_: int) -> dict:
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
    return occasion


def _scrape_occasions(schedule: dict, type_: Literal['event', 'venue']):
    ids: list[int] = []
    for day in schedule:
        for occasion in day[f'{type_}s']:
            ids.append(occasion['id'])

    occasions = []
    for i, id_ in enumerate(ids):
        logger.debug(f'Scraping details for {type_} {id_} ({i + 1}/{len(ids)})')

        try:
            occasion = _scrape_occasion(id_)
            occasions.append(occasion)
        # Skip failed scrapes.
        except TimeoutRetryError as exception:
            logger.error(f'Failed to get {type_} {id_}: {exception}')
            continue

        if (i + 1) % 20 == 0 or i == len(ids) - 1:
            logger.info(f'{i + 1}/{len(ids)} {type_}s scraped')

    logger.info(f'Scraped {len(occasions)}/{len(ids)} {type_}s')
    return occasions


def _find_event_sibling_id(sibling: Sibling, schedule: dict) -> int:
    start_hour, start_minute = sibling['start_time'].split(':')
    earliest_half_hour = int(start_minute) // 30 * 30
    sibling_time_slot = f'{start_hour}:{earliest_half_hour:02d}'

    day = next(
        (day for day in schedule if day['date'] == sibling['date']),
        None,
    )

    event = None
    for occasion in day['events']:
        start_hour, start_minute = sibling['start_time'].split(':')
        earliest_half_hour = int(start_minute) // 30 * 30
        occasion_time_slot = f'{start_hour}:{earliest_half_hour:02d}'

        if occasion['title'] == sibling['title'] and occasion_time_slot == sibling_time_slot:
            event = occasion
            break

    return event['id']


def _find_venue_sibling_id(sibling: Sibling, schedule: dict) -> int:
    day = next(
        (day for day in schedule if day['date'] == sibling['date']),
        None,
    )

    venue = next(
        (
            occasion
            for occasion in day['venues']
            if occasion['title'] == sibling['title']
            and occasion['start_time'] == sibling['start_time']
        ),
        None,
    )

    return venue['id']


def main():
    """Scrapes schedule, some events and a ticket, and only prints the result."""
    logging.basicConfig(
        filename=f'{__file__}.log',
        filemode='w',
        level=logging.DEBUG,
        style='{',
        format='{asctime}:{levelname}:{name}:{filename}:{lineno}:{message}',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(logging.Formatter('%(levelname)-8s %(message)s'))
    logging.getLogger().addHandler(console)

    # Scrape schedule
    print('The schedule:')
    schedule = scrape_schedule()

    # Scrape events until a ticket with a price is found
    has_scraped = False
    print('\nSome events:')
    for day in schedule:
        for event in day['events']:
            event_id = event['id']
            event = _scrape_occasion(event_id)
            if ticket_id := event.get('ticket_id'):
                print('\nA ticket:')
                scrape_ticket_price_range(ticket_id)
                has_scraped = True
                break
        if has_scraped:
            break


if __name__ == '__main__':
    main()
