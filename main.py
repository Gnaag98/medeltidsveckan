import json
import logging
from pathlib import Path

import requests

from src.log import *
from src.scrape import scrape_event, scrape_schedule, scrape_ticket_price_range

TIMEOUT_SECONDS = 5
NUM_RETRIES = 3

logger = logging.getLogger(__name__)


def get_sibling_id(sibling: dict, schedule: dict) -> int:
    date = sibling['date']
    start_time = sibling['start_time']
    start_hour, start_minute = start_time.split(':')
    title = sibling['title']

    earliest_half_hour = int(start_minute) // 30 * 30
    time_slot = f'{start_hour}:{earliest_half_hour:02d}'

    day = schedule[date]
    event = None
    # Try get time slot event.
    if events := day['times'].get(time_slot):
        event = next(
            (
                event
                for event in events
                if event['start_time'] == start_time and event['title'] == title
            ),
            None,
        )
    # Else get opening hours event.
    if event is None:
        events = day['opening_hours']
        event = next(
            event
            for event in events
            if event['start_time'] == start_time and event['title'] == title
        )
    return event['event_id']


def main():
    log_filepath = Path('main.log')
    data_directory = Path(__file__).parent / 'data'
    schedule_filepath = data_directory / 'simple_schedule.json'
    events_filepath = data_directory / 'events.json'

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
    try:
        schedule = scrape_schedule(timeout=TIMEOUT_SECONDS, verbose=True)
        with open(schedule_filepath, 'w', encoding='utf-8') as file:
            json.dump(schedule, file, ensure_ascii=False, indent=4)
        log_info_and_print('Schedule saved.')
    except requests.exceptions.ConnectTimeout:
        log_error_and_print('Timeout getting schedule')
    # """

    # Get and save events.
    # """
    log_info_and_print('Gettings events')
    with open(schedule_filepath, 'r') as file:
        schedule = json.load(file)
    event_ids: list[int] = []
    for day in schedule.values():
        for event in day['opening_hours']:
            event_ids.append(event['event_id'])
        for events in day['times'].values():
            for event in events:
                event_ids.append(event['event_id'])
    events = {}
    for event_id in event_ids:
        num_failed_attempts = 0
        event = None
        while event is None and num_failed_attempts < NUM_RETRIES:
            try:
                event = scrape_event(event_id, timeout=TIMEOUT_SECONDS, verbose=True)
                break
            except requests.exceptions.ReadTimeout:
                num_failed_attempts += 1
                log_warning_and_print(
                    f'Timeout getting event [{num_failed_attempts}/{NUM_RETRIES}]'
                )
        if event is None:
            log_error_and_print(f'Failed to get event {event_id}')
            continue
        events[event_id] = event
    log_info_and_print(f'Got {len(events)}/{len(event_ids)} events')
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    log_info_and_print('Events saved')
    # """

    # Update saved events with ticket prices.
    # """
    log_info_and_print('Updating saved events with ticket prices')
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    for event in events.values():
        if (ticket_id := event.get('ticket_id')) and (
            price_range := scrape_ticket_price_range(
                ticket_id, timeout=TIMEOUT_SECONDS, verbose=True
            )
        ):
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
    # """

    # Update saved events with sibling IDs.
    # """
    log_info_and_print('Updating saved events with sibling IDs')
    with open(schedule_filepath, 'r', encoding='utf-8') as file:
        schedule = json.load(file)
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    for event_id, event in events.items():
        if siblings := event.get('siblings'):
            print(event_id)
            for sibling in siblings:
                sibling_id = get_sibling_id(sibling, schedule)
                sibling['event_id'] = sibling_id
                print('-', sibling_id)
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    log_info_and_print('Updated saved events with sibling IDs')
    # """


if __name__ == '__main__':
    main()
