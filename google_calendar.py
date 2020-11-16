# TODO: Find a way to associate events to specific source calendars
# TODO: Figure out correct authentication scheme for servers
# TODO: Web interface

import argparse
import sys

import arrow
from googleapiclient import discovery

from constants import MY_CALENDAR_ID
from utils import get_logger, get_service_client, get_events_dict, json_pretty_print, get_entire_list, get_ics_calendars, notify_no_sources


def print_calendars(service):
    calendars = get_entire_list(service.calendarList().list, minAccessRole='writer')
    for calendar in calendars:
        print(
            f"{calendar['summary']:<20} "
            f"[{calendar['id']:<52}] "
            f"primary={calendar.get('primary', False)!s:<5}  "
            f"selected={calendar.get('selected', False)!s:<5}  "
            f"description={calendar.get('description', '')}"
        )


def print_events(service):
    """Prints all the events currently on the Google Calendar"""
    print(json_pretty_print(list(get_events_dict(service).values()), True))


def print_update_times(service):
    """Prints events IDs and when they were last updated"""
    print(json_pretty_print({event['id']: event['updated'] for event in get_events_dict(service).values()}, True))


def sync_calendar(service):
    logger = get_logger()

    logger.info('Started.')

    try:
        # Get all the events from the Google calendar
        all_events = get_events_dict(service)

        # Get events from Facebook using our custom iCal library
        try:
            src_calendars = get_ics_calendars()
        except Exception:
            logger.exception('Failed fetching source ICS!')
            return

        # Take care of this end case where the Facebook URL is stale
        if not src_calendars:
            notify_no_sources()
            logger.warning('No source calendars! Exiting.')
            return

        logger.info('Got {} calendar{}'.format(len(src_calendars), 's' if len(src_calendars) != 1 else ''))

        # Initiate the set of IDs to delete with all Google events
        events_to_delete = {k for k, v in all_events.items() if v['status'] != 'cancelled'}
        for src_calendar in src_calendars:
            logger.info('Calendar has {} event{}'.format(len(src_calendar.events), 's' if len(src_calendar.events) != 1 else ''))
            for src_event in src_calendar.events:
                # Make ID for event using its Facebook event ID
                event_id = src_event.uid[:src_event.uid.find('@')]

                logger.info('Source event. id={} summary={}'.format(event_id, src_event.name))

                # If Facebook event is found on Google, remove it from events_to_delete. Also skip updating it if there are no new updates for it from Facebook.
                dst_event = all_events.get(event_id)
                if dst_event:
                    events_to_delete.discard(event_id)
                    if (dst_event['status'] == 'cancelled' and src_event.status != 'CONFIRMED') or (src_event.last_modified and src_event.last_modified <= arrow.get(dst_event['updated'])):
                        logger.info('Skip. id={}'.format(event_id))
                        continue

                # Construct new Google event from Facebook data
                event = {'id': event_id,
                         'status': 'confirmed',
                         'summary': src_event.name,
                         'start': {'dateTime': src_event.begin.for_json()},
                         'source': {'title': 'Facebook event',
                                    'url': src_event.url}}

                if src_event.end:
                    event['end'] = {'dateTime': src_event.end.for_json()}
                if src_event.description:
                    event['description'] = src_event.description
                if src_event.location:
                    event['location'] = src_event.location

                logger.debug('Request body. id={} {}'.format(event_id, json_pretty_print(event)))

                # If event is existent, update. Otherwise, create new event.
                try:
                    if dst_event is None:
                        logger.info('Insert. id={}'.format(event_id))
                        event = service.events().insert(calendarId=MY_CALENDAR_ID, body=event).execute()
                    else:
                        logger.info('Update. id={}'.format(event_id))
                        event = service.events().update(calendarId=MY_CALENDAR_ID, eventId=event_id, body=event).execute()

                    logger.debug('Response. id={} {}'.format(event_id, json_pretty_print(event)))
                except discovery.HttpError as e:
                    logger.error('Error! id={} {}'.format(event_id, e))

        # Delete all Google events that aren't on Facebook
        for event_id in events_to_delete:
            logger.info('Delete. id={}'.format(event_id))
            try:
                service.events().delete(calendarId=MY_CALENDAR_ID, eventId=event_id).execute()
            except discovery.HttpError as e:
                logger.error('Error! id={} {}'.format(event_id, e))
    except Exception:
        logger.exception('General failure!')

    logger.info('Finished.')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-c', '--calendars', action='store_true')
    p.add_argument('-e', '--events', action='store_true')
    p.add_argument('-u', '--update-times', action='store_true')
    args = p.parse_args()

    logger = get_logger()

    try:
        service = get_service_client()
    except Exception:
        logger.exception('Failed initializing API!')
        sys.exit(1)

    if args.calendars:
        return print_calendars(service)

    if args.events:
        return print_events(service)

    if args.update_times:
        return print_update_times(service)

    return sync_calendar(service)


if __name__ == '__main__':
    main()
