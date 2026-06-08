from bs4 import BeautifulSoup
import requests


def main():
    # Get page.
    response = requests.get('https://www.medeltidsveckan.se/programme/')
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    # Get weekdays in correct locale.
    weekdays = tuple(button.text for button in soup.select('#day-list button'))

    # Get days.
    days = soup.select('.day')
    for day_index, day in enumerate(days):
        date_string = day.get('id').removeprefix('date-')
        weekday = weekdays[day_index]
        print(weekday, date_string)

        # Get time slots.
        time_views = day.select('.time-view')
        for time_view in time_views:
            time = time_view.select_one('h4')
            print(time.string)

            # Get events.
            for event in time_view.select('article'):
                title = event.select_one('strong').string
                event_id = int(event.get('data-pid'))

                # Get details.
                response = requests.get(
                    'https://www.medeltidsveckan.se',
                    params={
                        'action': 'fetch-programme-item',
                        'pid': event_id
                    }
                )
                response.raise_for_status()
                details = response.json()
                venue = details['sidebar']['venue']
                print(f'- [{event_id}] {title} ({venue})')

        print()


if __name__ == "__main__":
    main()
