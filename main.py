import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from src.scrape import scrape_events, scrape_schedule, scrape_ticket_price_range, scrape_venues

FILE_LOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO

logger = logging.getLogger(__name__)


class Sibling(TypedDict):
    date: str
    start_time: str
    title: str


def setup_logging(filepath: Path):
    """Setup logging to file and console."""

    logging.basicConfig(
        filename=filepath,
        level=FILE_LOG_LEVEL,
        style='{',
        format='{asctime}|{levelname}|{name}|{filename}:{lineno}|{message}',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    console = logging.StreamHandler()
    console.setLevel(CONSOLE_LOG_LEVEL)
    console.setFormatter(logging.Formatter('%(levelname)-8s %(message)s'))
    logging.getLogger().addHandler(console)


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


def add_sibling_ids(occasions: dict, schedule: dict, find_occasion_sibling_id: Callable):
    for occasion in occasions:
        if siblings := occasion.get('siblings'):
            for sibling in siblings:
                sibling_id = find_occasion_sibling_id(sibling, schedule)
                sibling['sibling_id'] = sibling_id
                logger.debug(f'Added sibling id {sibling_id} to {occasion["id"]}')


def main():
    log_filepath = Path('main.log')
    data_directory = Path(__file__).parent / 'data'
    schedule_filepath = data_directory / 'scraped_schedule.json'
    events_filepath = data_directory / 'scraped_events.json'
    venues_filepath = data_directory / 'scraped_venues.json'

    setup_logging(log_filepath)

    # Ensure data directory exists.
    data_directory.mkdir(exist_ok=True)

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
    add_sibling_ids(events, schedule, find_event_sibling_id)
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    logger.info('Updated saved events with sibling IDs')

    # Update venues.
    logger.info('Updating saved venues with sibling IDs')
    with open(venues_filepath, 'r', encoding='utf-8') as file:
        venues = json.load(file)
        add_sibling_ids(venues, schedule, find_venue_sibling_id)
    with open(venues_filepath, 'w', encoding='utf-8') as file:
        json.dump(venues, file, ensure_ascii=False, indent=4)
    logger.info('Updated saved venues with sibling IDs')
    # """


if __name__ == '__main__':
    main()
