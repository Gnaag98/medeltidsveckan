import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from src.log import *
from src.scrape import scrape_events, scrape_schedule, scrape_ticket_price_range, scrape_venues

logger = logging.getLogger(__name__)


class Sibling(TypedDict):
    date: str
    start_time: str
    title: str


def add_ticket_prices(events_filepath: Path, *, verbose=False):
    log_info_and_print('Updating saved events with ticket prices')
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    for i, event in enumerate(events):
        if ticket_id := event.get('ticket_id'):
            if verbose:
                print(f'Event {i + 1}/{len(events)} ({event["id"]}):')
            if price_range := scrape_ticket_price_range(ticket_id, verbose=verbose):
                min_price = price_range[0]
                max_price = price_range[1]
                if min_price == max_price:
                    event['price'] = max_price
                else:
                    event['min_price'] = min_price
                    event['max_price'] = max_price
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    log_info_and_print('Updated saved events with ticket prices')


def find_event_sibling_id(sibling: Sibling, schedule: dict) -> int:
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


def find_venue_sibling_id(sibling: Sibling, schedule: dict) -> int:
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


def add_sibling_ids(
    occasions: dict, schedule: dict, find_occasion_sibling_id: Callable, verbose=False
):
    for occasion in occasions:
        if siblings := occasion.get('siblings'):
            if verbose:
                print(f'Siblings of {occasion["id"]}:')
            for sibling in siblings:
                sibling_id = find_occasion_sibling_id(sibling, schedule)
                sibling['sibling_id'] = sibling_id
                if verbose:
                    print('-', sibling_id)


def main():
    log_filepath = Path('main.log')
    data_directory = Path(__file__).parent / 'data'
    schedule_filepath = data_directory / 'scraped_schedule.json'
    events_filepath = data_directory / 'scraped_events.json'
    venues_filepath = data_directory / 'scraped_venues.json'

    # Setup logger.
    logging.basicConfig(
        filename=log_filepath,
        level=logging.INFO,
        style='{',
        format='{asctime}:{levelname}:{name}:{filename}:{lineno}:{message}',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Ensure data directory exists.
    data_directory.mkdir(exist_ok=True)

    # Parse and save simple schedule.
    # """
    log_info_and_print('Gettings schedule')
    schedule = scrape_schedule()
    with open(schedule_filepath, 'w', encoding='utf-8') as file:
        json.dump(schedule, file, ensure_ascii=False, indent=4)
    log_info_and_print('Schedule saved.')
    # """

    # Get and save events and venues.
    # """
    with open(schedule_filepath, 'r') as file:
        schedule = json.load(file)

    events = scrape_events(schedule)
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    log_info_and_print('Events saved')

    # Get and save venues (opening hours).
    venues = scrape_venues(schedule)
    with open(venues_filepath, 'w', encoding='utf-8') as file:
        json.dump(venues, file, ensure_ascii=False, indent=4)
    log_info_and_print('Venues saved')
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
    log_info_and_print('Updating saved events with sibling IDs')
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    add_sibling_ids(events, schedule, find_event_sibling_id)
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    log_info_and_print('Updated saved events with sibling IDs')

    # Update venues.
    log_info_and_print('Updating saved venues with sibling IDs')
    with open(venues_filepath, 'r', encoding='utf-8') as file:
        venues = json.load(file)
        add_sibling_ids(venues, schedule, find_venue_sibling_id)
    with open(venues_filepath, 'w', encoding='utf-8') as file:
        json.dump(venues, file, ensure_ascii=False, indent=4)
    log_info_and_print('Updated saved venues with sibling IDs')
    # """


if __name__ == '__main__':
    main()
