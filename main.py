from collections.abc import Iterable, Iterator
import datetime
from html import unescape
import json
from pathlib import Path

from bs4 import BeautifulSoup
import requests

TIMEOUT_SECONDS = 5
NUM_RETRIES = 3


def get_simple_schedule(url: str, verbose=False) -> dict:
    dates = {}

    # Get page.
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    # Get weekdays in correct locale.
    weekdays = tuple(button.text for button in soup.select('#day-list button'))

    # Get days.
    days = soup.select('.day')
    for day_index, day_element in enumerate(days):
        times = {}
        date_string = day_element.get('id').removeprefix('date-')
        if verbose:
            weekday = weekdays[day_index]
            print(weekday, date_string)

        # Get time slots.
        time_views = day_element.select('.time-view')
        for time_view in time_views:
            events = []
            time_string = time_view.select_one('h4').string
            if verbose:
                print('-', time_string)

            # Get events.
            for event in time_view.select('article'):
                event_id = int(event['data-pid'])
                title = unescape(event.select_one('strong').string)
                if verbose:
                    print('  -', event_id, title)
                events.append({
                    'event_id': event_id,
                    'title': title,
                })

            times[time_string] = events
        dates[date_string] = times
    return dates


def get_event(url: str, event_id: int, quiet=False, verbose=False) -> dict:
    # Get json.
    response = requests.get(
        url,
        params={
            'action': 'fetch-programme-item',
            'pid': event_id
        },
        timeout=TIMEOUT_SECONDS
    )
    response.raise_for_status()
    details = response.json()

    # Parse event details.
    event = {}
    if image_url := details.get('image'):
        event['image_url'] = image_url
    if item_owner := details['header']['item_owner']:
        event['owner'] = unescape(item_owner)
    event['title'] = unescape(details['header']['title'])
    event['html_escaped_description'] = details['content']['description']
    if siblings := details['content']['siblings']:
        event['siblings'] = []
        for sibling in siblings.values():
            timestamp = int(sibling['timestamp'])
            date = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).date()
            event['siblings'].append({
                'date': str(date),
                'weekday': unescape(sibling['day']),
                'start_time': unescape(sibling['time']),
                'title': unescape(sibling['title']),
            })
    event['weekday'] = details['sidebar']['dayName']
    event['date'] = details['sidebar']['date']
    start, end = details['sidebar']['time'].split(' - ')
    event['start_time'] = unescape(start)
    event['end_time'] = unescape(end)
    event['venue'] = unescape(details['sidebar']['venue'])
    if ticket_url := details['sidebar']['ticket_link']:
        ticket_id = int(ticket_url.split('/')[-1])
        event['ticket_id'] = ticket_id
    if not quiet:
        if verbose:
            print(json.dumps(event, indent=4, ensure_ascii=False))
        else:
            print('-', event_id, event['weekday'], event['start_time'], event['title'])

    # DEBUG validation.
    for k, v in event.items():
        if v is None:
            print(json.dumps(event, indent=4, ensure_ascii=False))
            raise RuntimeError(f'{k} in event {event_id} is None')
        if v == "":
            print(json.dumps(event, indent=4, ensure_ascii=False))
            raise RuntimeError(f'{k} in event {event_id} is empty')

    return event


def get_ticket_price_range(ticket_id: int, quiet=False) -> tuple[int, int] | None:
    # Get json.
    url = f'https://www.nortic.se/api/json/show/{ticket_id}'
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()

    # Get price range.
    events = data['events']
    if len(events) == 0:
        return None
    show = events[0]['shows'][0]
    min_price = int(float(show['minPrice']))
    max_price = int(float(show['maxPrice']))
    if not quiet:
        print(f'{ticket_id}: ', end='')
        if min_price == max_price:
            print(f'{min_price:4d}')
        else:
            print(f'{min_price:4d} - {max_price:4d}')

    return (min_price, max_price)


def main():
    program_url = 'https://www.medeltidsveckan.se/programme/'
    details_url = 'https://www.medeltidsveckan.se/'
    data_directory = Path(__file__).parent / 'data'
    schedule_filepath = data_directory / 'simple_schedule.json'
    events_filepath = data_directory / 'events.json'

    # Ensure data directory exists.
    data_directory.mkdir(exist_ok=True)

    # Parse and save simple schedule.
    #"""
    print('Gettings schedule.')
    try:
        schedule = get_simple_schedule(program_url)
        with open(schedule_filepath, 'w', encoding='utf-8') as file:
            json.dump(schedule, file, ensure_ascii=False, indent=4)
        print('Schedule saved.')
    except requests.exceptions.ConnectTimeout:
        print('Timeout gettings schedule. Skipping to next step.')
    #"""

    # Get and save events.
    #"""
    print('Gettings events')
    with open(schedule_filepath, 'r') as file:
        schedule = json.load(file)
    event_ids: list[int] = []
    for times in schedule.values():
        for events in times.values():
            for event in events:
                event_ids.append(event['event_id'])
    events = {}
    for event_id in event_ids:
        num_failed_attempts = 0
        event = None
        while event is None and num_failed_attempts < NUM_RETRIES:
            try:
                event = get_event(details_url, event_id)
            except requests.exceptions.ReadTimeout:
                num_failed_attempts += 1
                print(f'Attempt {num_failed_attempts}/{NUM_RETRIES} to get info for event {event_id} timeout.')
            break
        if event is None:
            print(f'Failed to parse event {event_id}.')
            continue
        events[event_id] = event
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    print(f'Events saved.')
    #"""

    # Update saved events with ticket prices.
    #"""
    print('Updating saved events with ticket prices')
    with open(events_filepath, 'r', encoding='utf-8') as file:
        events = json.load(file)
    for event in events.values():
        if ticket_id := event.get('ticket_id'):
            if price_range := get_ticket_price_range(ticket_id):
                min_price = price_range[0]
                max_price = price_range[1]
                if min_price == max_price:
                    event['price'] = max_price
                else:
                    event['min_price'] = min_price
                    event['max_price'] = max_price
    with open(events_filepath, 'w', encoding='utf-8') as file:
        json.dump(events, file, ensure_ascii=False, indent=4)
    print('Updated saved events with ticket prices.')
    #"""


if __name__ == "__main__":
    main()
