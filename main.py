from collections.abc import Iterable, Iterator
import datetime
from html import unescape
import json
from pathlib import Path

from bs4 import BeautifulSoup
import requests

TIMEOUT_SECONDS = 3
NUM_RETRIES = 3


def get_ids(url: str, verbose=False) -> dict:
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
            ids = []
            time_string = time_view.select_one('h4').string
            if verbose:
                print('-', time_string)

            # Get events.
            for event in time_view.select('article'):
                event_id = int(event.get('data-pid'))
                if verbose:
                    print('  -', event_id)
                ids.append(event_id)

            times[time_string] = ids
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
            date = datetime.date.fromtimestamp(timestamp)
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
        event['ticket_url'] = ticket_url
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


def main():
    program_url = 'https://www.medeltidsveckan.se/programme/'
    details_url = 'https://www.medeltidsveckan.se/'
    ids_filepath = Path(__file__).parent / 'event_ids.json'
    events_filepath = Path(__file__).parent / 'events_v1.json'

    # Parse and save event IDs.
    print('Gettings IDs')
    event_ids: list[int] | None = None
    try:
        event_ids = get_ids(program_url)
        with open(ids_filepath, 'w') as file:
            json.dump(event_ids, file, indent=4)
        print('IDs saved.')
    except requests.exceptions.ConnectTimeout:
        print('Timeout gettings event IDs. Skipping to next step.')

    # Get and save events.
    print('Gettings events')
    with open(ids_filepath, 'r') as file:
        event_ids_by_date = json.load(file)
        event_ids: list[int] = []
        for times in event_ids_by_date.values():
            for ids in times.values():
                event_ids.extend(ids)
    print('IDs loaded from file.')

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


if __name__ == "__main__":
    main()
