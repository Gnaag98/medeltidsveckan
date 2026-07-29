import logging
from pathlib import Path

from src.scrape import scrape

FILE_LOG_LEVEL = logging.INFO
CONSOLE_LOG_LEVEL = logging.INFO

logger = logging.getLogger(__name__)


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


def main():
    log_filepath = Path('main.log')
    data_directory = Path(__file__).parent / 'data'
    schedule_filepath = data_directory / 'scraped_schedule.json'
    events_filepath = data_directory / 'scraped_events.json'
    venues_filepath = data_directory / 'scraped_venues.json'

    setup_logging(log_filepath)

    # Ensure data directory exists.
    data_directory.mkdir(exist_ok=True)

    scrape(
        schedule_filepath=schedule_filepath,
        events_filepath=events_filepath,
        venues_filepath=venues_filepath,
    )


if __name__ == '__main__':
    main()
