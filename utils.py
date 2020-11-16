import json
import logging
import os
import pickle
import urllib.request
from logging.handlers import RotatingFileHandler

import ics
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient import discovery



import constants


def get_logger():
    logger = logging.getLogger()

    if len(logger.handlers) == 2:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter('%(asctime)s,%(levelname)s,%(lineno)s,%(message)s')

    for handler in logger.handlers:
        logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(constants.LOG_PATH, maxBytes=constants.LOG_SIZE, backupCount=10, encoding='utf8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    return logger


def json_pretty_print(o, pretty=False):
    kwargs = dict(
        separators=(',', ':'),
        sort_keys=True,
        ensure_ascii=False,
    )

    if pretty:
        kwargs.update(indent=2)

    return json.dumps(o, **kwargs)


def get_service_client():
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', ['https://www.googleapis.com/auth/calendar'])
            # creds = flow.run_local_server(port=0)
            creds = flow.run_console()

        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return discovery.build('calendar', 'v3', credentials=creds)


def get_entire_list(func, **kw):
    page_token = None
    ret = []
    while True:
        page = func(pageToken=page_token, **kw).execute()
        ret += page['items']
        page_token = page.get('nextPageToken')
        if not page_token:
            break
    return ret


def get_events_dict(service):
    return {e['id']: e for e in get_entire_list(service.events().list, calendarId=constants.MY_CALENDAR_ID, showDeleted=True)}


def notify_no_sources():
    logger = get_logger()

    try:
        from constants import NOTIFICATION_FILE, IFTTT_MAKER_KEY, IFTTT_MAKER_EVENT
        import pyfttt
    except ImportError:
        logger.exception('Failed importing notification stuff!')
        return

    try:
        with open(NOTIFICATION_FILE) as f:
            u = f.read().strip()
    except Exception:
        logger.exception('Failed reading notification file!')
        u = None

    if u == MY_ICS_URL:
        logger.info('IFTTT event already triggered.')
        return

    try:
        pyfttt.send_event('dNSxTcir9cIXus2UBo98Xm', 'fb_google_calendar_expired')
    except Exception:
        logger.exception('Failed sending IFTTT event trigger!')
        return

    try:
        with open(NOTIFICATION_FILE, 'w') as f:
            f.write(MY_ICS_URL)
    except Exception:
        logger.exception('Failed writing notification file!')

    logger.info('Successfully triggered IFTTT event.')


def get_ics_calendars():
    response = urllib.request.urlopen(constants.MY_ICS_URL)
    content = response.read().decode(response.headers.get_content_charset())
    return ics.Calendar.parse_multiple(content)
