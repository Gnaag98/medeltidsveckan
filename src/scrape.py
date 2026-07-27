import datetime
import logging
from html import unescape

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def scrape_schedule(*, timeout: float, verbose=False) -> dict:
    dates = {}
    num_events = 0

    # Get page.
    url = 'https://www.medeltidsveckan.se/programme/'
    logger.info(f'Getting schedule from {url}')
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    # Get weekdays in correct locale.
    weekdays = tuple(button.text for button in soup.select('#day-list button'))

    # Get days.
    days = soup.select('.day')
    for day_index, day_element in enumerate(days):
        day = {
            'opening_hours': [],
            'times': {},
        }
        date_string = day_element.get('id').removeprefix('date-')
        if verbose:
            weekday = weekdays[day_index]
            print(weekday, date_string)

        # Get opening hours.
        if hours_element := day_element.select_one(f'#hours-{date_string}'):
            for hour_element in hours_element.select('a'):
                time_element, title_element = hour_element.select('div')
                start_time, end_time = time_element.string.split('-')
                day['opening_hours'].append(
                    {
                        'event_id': int(hour_element['data-pid']),
                        'title': title_element.string,
                        'start_time': start_time,
                        'end_time': end_time,
                    }
                )

        # Get time slots.
        time_views = day_element.select('.time-view')
        for time_view in time_views:
            events = []
            time_slot = time_view.select_one('h4').string
            if verbose:
                print('-', time_slot)

            # Get events.
            for article in time_view.select('article'):
                event = {}
                event_id = int(article['data-pid'])
                event['event_id'] = event_id
                event['title'] = unescape(article.select_one('strong').string)
                event['start_time'] = article.select_one('span').string
                if footer := article.select_one('.card-footer').string:
                    event['category'] = footer.strip()
                if verbose:
                    print('  -', event['event_id'], event['title'])
                events.append(event)
                num_events += 1

            day['times'][time_slot] = events
        dates[date_string] = day
    logger.info(f'Schedule contains {num_events} events')
    return dates


def scrape_event(event_id: int, *, timeout: float, verbose=False) -> dict:
    # Get json.
    url = 'https://www.medeltidsveckan.se/'
    response = requests.get(
        url,
        params={
            'action': 'fetch-programme-item',
            'pid': event_id,
        },
        timeout=timeout,
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
            event['siblings'].append(
                {
                    'date': str(date),
                    'weekday': unescape(sibling['day']),
                    'start_time': unescape(sibling['time']),
                    'title': unescape(sibling['title']),
                }
            )
    event['weekday'] = details['sidebar']['dayName']
    event['date'] = details['sidebar']['date']
    start, end = details['sidebar']['time'].split(' - ')
    event['start_time'] = unescape(start)
    event['end_time'] = unescape(end)
    event['venue'] = unescape(details['sidebar']['venue'])
    if ticket_url := details['sidebar']['ticket_link']:
        ticket_id = int(ticket_url.split('/')[-1])
        event['ticket_id'] = ticket_id
    if verbose:
        print('-', event_id, event['weekday'], event['start_time'], event['title'])
    return event


def scrape_ticket_price_range(
    ticket_id: int, *, timeout: float, verbose=False
) -> tuple[int, int] | None:
    # Get json.
    url = f'https://www.nortic.se/api/json/show/{ticket_id}'
    response = requests.get(url, timeout=timeout)
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


def main():
    """Scrapes schedule and some events and only prints the result."""
    logging.basicConfig(
        filename=f'{__file__}.log',
        level=logging.INFO,
        style='{',
        format='{asctime}:{levelname}:{name}:{filename}:{lineno}:{message}',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    # Scrape schedule
    print('The schedule:')
    schedule = scrape_schedule(timeout=5.0, verbose=True)

    # Scrape events until a ticket with a price is found.
    has_scraped = False
    print('\nSome events:')
    for day in schedule.values():
        for events in day['times'].values():
            for event in events:
                event_id = event['event_id']
                event = scrape_event(event_id, timeout=5.0, verbose=True)
                if ticket_id := event.get('ticket_id'):
                    print('\nA ticket:')
                    scrape_ticket_price_range(ticket_id, timeout=5.0, verbose=True)
                    has_scraped = True
                    break
            if has_scraped:
                break
        if has_scraped:
            break


if __name__ == '__main__':
    main()
