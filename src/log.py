import logging

logger = logging.getLogger(__name__)


def log_debug_and_print(message: str):
    logger.debug(message)
    print(message)


def log_info_and_print(message: str):
    logger.info(message)
    print(message)


def log_warning_and_print(message: str):
    logger.warning(message)
    print(message)


def log_error_and_print(message: str):
    logger.error(message)
    print(message)
