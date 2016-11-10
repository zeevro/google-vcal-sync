# TODO: Find a way to associate events to specific source calendars
# TODO: Figure out correct authentication scheme for servers
# TODO: Web interface

from __future__ import print_function

import httplib2
import os
import dateutil
import logging.handlers
import ical

import json

from apiclient import discovery
import oauth2client
from oauth2client import client
from oauth2client import tools

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None

from constants import APPLICATION_NAME, CLIENT_SECRET_FILE, MY_CALENDAR_ID, MY_ICS_URL, LOG_PATH, LOG_SIZE


_logger = None


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

    file_handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=LOG_SIZE, backupCount=10, encoding='utf8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    return logger


def j(o, pretty=False):
    if pretty:
        return json.dumps(o, separators=(',', ': '), indent=2, sort_keys=True)

    return json.dumps(o, separators=(',', ':'), sort_keys=True)


def get_credentials():
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    credential_dir = os.path.join(os.path.expanduser('~'), '.credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir, 'calendar-python-quickstart.json')

    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, 'https://www.googleapis.com/auth/calendar')
        flow.user_agent = APPLICATION_NAME
        if flags:
            credentials = tools.run_flow(flow, store, flags)
        else:  # Needed only for compatibility with Python 2.6
            credentials = tools.run(flow, store)
        print('Storing credentials to ' + credential_path)
    return credentials


def translate_dt(s):
    return dateutil.parser.parse(s).strftime('%Y-%m-%dT%H:%M:%S%z')


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


def main():
    logger = get_logger()

    logger.info('Started.')

    try:
        try:
            credentials = get_credentials()
            http = credentials.authorize(httplib2.Http())
            service = discovery.build('calendar', 'v3', http=http)
        except Exception:
            logger.exception('Failed initializing API!')
            return

        if 0:
            calendars = get_entire_list(service.calendarList().list, minAccessRole='writer')
            for calendar in calendars:
                print('%-20s [%-52s] primary=%-5s  selected=%-5s  description=%s' % (calendar['summary'],
                                                                                     calendar['id'],
                                                                                     calendar.get('primary', False),
                                                                                     calendar.get('selected', False),
                                                                                     calendar.get('description', '')))
            return

        if 0:
            try:
                service.calendars().delete(calendarId=MY_CALENDAR_ID).execute()
            except discovery.HttpError as e:
                if e.resp['status'] != '404':
                    raise
            primary_calendar = service.calendars().get(calendarId='primary').execute()
            print(j(service.calendars().insert(body={'summary': 'Facebook', 'timeZone': primary_calendar['timeZone']}).execute(), True))
            return

        all_events = {e['id']: e for e in get_entire_list(service.events().list, calendarId=MY_CALENDAR_ID, showDeleted=True)}

        if 0:
            print(j(all_events.values()))
            return

        if 0:
            print(j({event['id']: event['updated'] for event in all_events.values()}, True))
            return

        try:
            src_calendars = ical.get_url_tree(MY_ICS_URL)
        except Exception:
            logger.exception('Failed fetching source ICS!')
            return

        if not src_calendars:
            logger.warning('No source calendars! Exiting.')
            return

        logger.info('Got %d calendar%s' % (len(src_calendars), 's' if len(src_calendars) != 1 else ''))

        events_to_delete = {k for k, v in all_events.iteritems() if v['status'] != 'cancelled'}
        for src_calendar in src_calendars:
            logger.info('Calendar has %d event%s' % (len(src_calendar['_items']), 's' if len(src_calendar['_items']) != 1 else ''))
            for src_event in src_calendar['_items']:
                event_id = src_event['UID'][:src_event['UID'].find('@')]

                logger.info('Source event. id=%s summary=%s' % (event_id, src_event['SUMMARY']))

                dst_event = all_events.get(event_id)
                if dst_event:
                    events_to_delete.discard(event_id)
                    if dst_event['status'] == 'cancelled' or ('LAST-MODIFIED' in src_event and dateutil.parser.parse(src_event['LAST-MODIFIED']) <= dateutil.parser.parse(dst_event['updated'])):
                        logger.info('Skip. id=%s' % event_id)
                        continue

                event = {'id': event_id,
                         'status': 'confirmed',
                         'summary': src_event['SUMMARY'],
                         'start': {'dateTime': translate_dt(src_event['DTSTART'])},
                         'source': {'title': 'Facebook event',
                                    'url': src_event['URL']}}

                if 'DTEND' in src_event:
                    event['end'] = {'dateTime': translate_dt(src_event['DTEND'])}
                if 'DESCRIPTION' in src_event:
                    event['description'] = src_event['DESCRIPTION']
                if 'LOCATION' in src_event:
                    event['location'] = src_event['LOCATION']

                logger.debug('Request body. id=%s %s' % (event_id, j(event)))

                try:
                    if dst_event is None:
                        logger.info('Insert. id=%s' % event_id)
                        event = service.events().insert(calendarId=MY_CALENDAR_ID, body=event).execute()
                    else:
                        logger.info('Update. id=%s' % event_id)
                        event = service.events().update(calendarId=MY_CALENDAR_ID, eventId=event_id, body=event).execute()

                    logger.debug('Response. id=%s %s' % (event_id, j(event)))
                except discovery.HttpError as e:
                    logger.error('Error! id=%s %s' % (event_id, e))

        for event_id in events_to_delete:
            logger.info('Delete. id=%s' % event_id)
            try:
                service.events().delete(calendarId=MY_CALENDAR_ID, eventId=event_id).execute()
            except discovery.HttpError as e:
                logger.error('Error! id=%s %s' % (event_id, e))
    except Exception:
        logger.exception('General failure!')

    logger.info('Finished.')


if __name__ == '__main__':
    main()
