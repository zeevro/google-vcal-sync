# TODO: Find a way to associate events to specific source calendars
# TODO: Figure out correct authentication scheme for servers
# TODO: Web interface


import httplib2
import os
import dateutil
import json
import argparse
import logging.handlers
import oauth2client.file

from apiclient import discovery
from oauth2client import client
from oauth2client import tools

import ical

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
        flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
        flow = client.flow_from_clientsecrets(os.path.normpath(os.path.expanduser(CLIENT_SECRET_FILE)), 'https://www.googleapis.com/auth/calendar')
        flow.user_agent = APPLICATION_NAME
        credentials = tools.run_flow(flow, store, flags)
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


def main():
    logger = get_logger()

    logger.info('Started.')

    try:
        # This is Google's stuff. Logs you into the service and gets the service API object.
        try:
            credentials = get_credentials()
            http = credentials.authorize(httplib2.Http())
            service = discovery.build('calendar', 'v3', http=http)
        except Exception:
            logger.exception('Failed initializing API!')
            return

        if 0:
            # Enable this to get a list of your calendars. This is used to set which calendar to use for Facebook events.
            calendars = get_entire_list(service.calendarList().list, minAccessRole='writer')  # pylint:disable=no-member
            for calendar in calendars:
                print('%-20s [%-52s] primary=%-5s  selected=%-5s  description=%s' % (calendar['summary'],
                                                                                     calendar['id'],
                                                                                     calendar.get('primary', False),
                                                                                     calendar.get('selected', False),
                                                                                     calendar.get('description', '')))
            return

        if 0:
            # I thik this makes a new calendar and prints its ID
            try:
                service.calendars().delete(calendarId=MY_CALENDAR_ID).execute()  # pylint:disable=no-member
            except discovery.HttpError as e:
                if e.resp['status'] != '404':
                    raise
            primary_calendar = service.calendars().get(calendarId='primary').execute()  # pylint:disable=no-member
            print(j(service.calendars().insert(body={'summary': 'Facebook', 'timeZone': primary_calendar['timeZone']}).execute(), True))  # pylint:disable=no-member
            return

        # Get all the events from the Google calendar
        all_events = {e['id']: e for e in get_entire_list(service.events().list, calendarId=MY_CALENDAR_ID, showDeleted=True)}  # pylint:disable=no-member

        if 0:
            # This prints all the events currently on the Google Calendar
            print(j(list(all_events.values())))
            return

        if 0:
            # This prints events IDs and when they were last updated
            print(j({event['id']: event['updated'] for event in all_events.values()}, True))
            return

        # Get events from Facebook using our custom iCal library
        try:
            src_calendars = ical.get_url_tree(MY_ICS_URL)
        except Exception:
            logger.exception('Failed fetching source ICS!')
            return

        # Take care of this end case where the Facebook URL is stale
        if not src_calendars:
            notify_no_sources()
            logger.warning('No source calendars! Exiting.')
            return

        logger.info('Got %d calendar%s' % (len(src_calendars), 's' if len(src_calendars) != 1 else ''))

        # Initiate the set of IDs to delete with all Google events
        events_to_delete = {k for k, v in all_events.items() if v['status'] != 'cancelled'}
        for src_calendar in src_calendars:
            logger.info('Calendar has %d event%s' % (len(src_calendar['_items']), 's' if len(src_calendar['_items']) != 1 else ''))
            for src_event in src_calendar['_items']:
                # Make ID for event using its Facebook event ID
                event_id = src_event['UID'][:src_event['UID'].find('@')]

                logger.info('Source event. id=%s summary=%s' % (event_id, src_event['SUMMARY']))

                # If Facebook event is found on Google, remove it from events_to_delete. Also skip updating it if there are no new updates for it from Facebook.
                dst_event = all_events.get(event_id)
                if dst_event:
                    events_to_delete.discard(event_id)
                    if (dst_event['status'] == 'cancelled' and src_event['STATUS'] != 'CONFIRMED') or ('LAST-MODIFIED' in src_event and dateutil.parser.parse(src_event['LAST-MODIFIED']) <= dateutil.parser.parse(dst_event['updated'])):
                        logger.info('Skip. id=%s' % event_id)
                        continue

                # Construct new Google event from Facebook data
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

                # If event is existent, update. Otherwise, create new event.
                try:
                    if dst_event is None:
                        logger.info('Insert. id=%s' % event_id)
                        event = service.events().insert(calendarId=MY_CALENDAR_ID, body=event).execute()  # pylint:disable=no-member
                    else:
                        logger.info('Update. id=%s' % event_id)
                        event = service.events().update(calendarId=MY_CALENDAR_ID, eventId=event_id, body=event).execute()  # pylint:disable=no-member

                    logger.debug('Response. id=%s %s' % (event_id, j(event)))
                except discovery.HttpError as e:
                    logger.error('Error! id=%s %s' % (event_id, e))

        # Delete all Google events that aren't on Facebook
        for event_id in events_to_delete:
            logger.info('Delete. id=%s' % event_id)
            try:
                service.events().delete(calendarId=MY_CALENDAR_ID, eventId=event_id).execute()  # pylint:disable=no-member
            except discovery.HttpError as e:
                logger.error('Error! id=%s %s' % (event_id, e))
    except Exception:
        logger.exception('General failure!')

    logger.info('Finished.')


if __name__ == '__main__':
    main()
