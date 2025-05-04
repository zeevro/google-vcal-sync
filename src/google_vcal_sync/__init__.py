# TODO: Find a way to associate events to specific source calendars
# TODO: Figure out correct authentication scheme for servers
# TODO: Web interface
# TODO: Better config (file/env/.env/command-line)

import argparse
from collections.abc import Callable, Generator
import dataclasses
import json
import logging
import pathlib
import pickle
from typing import TYPE_CHECKING, Protocol, TypedDict, cast
import urllib.request

import arrow
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient import discovery
from googleapiclient.errors import HttpError
import ics
import platformdirs


if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials
    from googleapiclient._apis.calendar.v3.resources import CalendarResource
    from googleapiclient._apis.calendar.v3.schemas import Event


MYDIR = pathlib.Path(__file__).parent


logger = logging.getLogger()


class J:
    def __init__(self, obj: object) -> None:
        self.obj = obj

    def __str__(self) -> str:
        return json.dumps(self.obj, ensure_ascii=False, sort_keys=True, indent=2)

    def __repr__(self) -> str:
        return json.dumps(self.obj, ensure_ascii=False, separators=(',', ':'))


@dataclasses.dataclass
class Config:
    ics_url: str
    calendar_id: str


class ItemsResponse[T](TypedDict, total=False):
    items: list[T]


class ItemsHttpRequest[T](Protocol):
    def execute(self, *args: ..., **kwargs: ...) -> ItemsResponse[T]: ...


class SupportsPagination[**P, T](Protocol):
    def list(self, *args: P.args, **kwargs: P.kwargs) -> ItemsHttpRequest[T]: ...
    def list_next(self, previous_request: ..., previous_response: ...) -> ItemsHttpRequest[T] | None: ...


def _paginate[**P, T](resource: SupportsPagination[P, T] | Callable[[], SupportsPagination[P, T]], *args: P.args, **kwargs: P.kwargs) -> Generator[T]:
    if callable(resource):
        resource = resource()
    req = resource.list(*args, **kwargs)
    while req is not None:
        resp = req.execute()
        yield from resp.get('items') or ()
        req = resource.list_next(req, resp)


def get_service_client(credentials_path: pathlib.Path, storage_dir: pathlib.Path) -> 'CalendarResource':
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    token_path = storage_dir / 'token.pickle'

    try:
        with token_path.open('rb') as f:
            creds = cast('Credentials', pickle.load(f))
    except Exception:
        creds = None

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, ['https://www.googleapis.com/auth/calendar'])
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with token_path.open('wb') as token:
            pickle.dump(creds, token)

    return discovery.build('calendar', 'v3', credentials=creds)


def get_events_dict(service: 'CalendarResource', config: Config) -> dict[str, 'Event']:
    return {eid: e for e in _paginate(service.events, calendarId=config.calendar_id, showDeleted=True) if (eid := e.get('id'))}


def get_ics_calendars(ics_url: str) -> list[ics.Calendar]:
    if not ics_url:
        raise ValueError('No URL')
    response = urllib.request.urlopen(ics_url)
    content = response.read().decode(response.headers.get_content_charset())
    return ics.Calendar.parse_multiple(content)


def print_calendars(service: 'CalendarResource', _config: Config) -> None:
    for calendar in _paginate(service.calendarList, minAccessRole='writer'):
        print(  # noqa: T201
            f'{calendar.get("summary"):<20} '
            f'[{calendar.get("id"):<52}] '
            f'primary={calendar.get("primary", False)!s:<5}  '
            f'selected={calendar.get("selected", False)!s:<5}  '
            f'description={calendar.get("description", "")}'
        )


def print_events(service: 'CalendarResource', config: Config) -> None:
    """Prints all the events currently on the Google Calendar"""
    print(J(list(get_events_dict(service, config).values())))  # noqa: T201


def print_update_times(service: 'CalendarResource', config: Config) -> None:
    """Prints events IDs and when they were last updated"""
    print(J({eid: e.get('updated') for eid, e in get_events_dict(service, config).items()}))  # noqa: T201


def sync_calendar(service: 'CalendarResource', config: Config) -> None:
    logger.info('Started.')

    try:
        # Get all the events from the Google calendar
        all_events = get_events_dict(service, config)

        # Get events from Facebook using our custom iCal library
        try:
            src_calendars = get_ics_calendars(config.ics_url)
        except Exception:
            logger.exception('Failed fetching source ICS!')
            return

        # Take care of this end case where the Facebook URL is stale
        if not src_calendars:
            logger.warning('No source calendars! Exiting.')
            return

        logger.info('Got %d calendar%s', len(src_calendars), 's' if len(src_calendars) != 1 else '')

        # Initiate the set of IDs to delete with all Google events
        events_to_delete = {k for k, v in all_events.items() if v.get('status') != 'cancelled'}
        for src_calendar in src_calendars:
            logger.info('Calendar has %d event%s', len(src_calendar.events), 's' if len(src_calendar.events) != 1 else '')
            for src_event in src_calendar.events:
                # Make ID for event using its Facebook event ID
                event_id = src_event.uid[: src_event.uid.find('@')]

                logger.info('Source event. id=%s summary=%s', event_id, src_event.name)

                # If Facebook event is found on Google, remove it from events_to_delete. Also skip updating it if there are no new updates for it from Facebook.
                dst_event = all_events.get(event_id)
                if dst_event:
                    logger.debug('src_event.status=%r src_event.last_modified=%r', src_event.status, src_event.last_modified)
                    logger.debug("dst_event.get('status')=%r arrow.get(dst_event.get('updated', 0))=%r", dst_event.get('status'), arrow.get(dst_event.get('updated', 0)))
                    logger.debug('dst_event=%r', J(dst_event))
                    events_to_delete.discard(event_id)
                    if (dst_event.get('status') == 'cancelled' and src_event.status != 'CONFIRMED') or (
                        src_event.last_modified and src_event.last_modified <= arrow.get(dst_event.get('updated', 0))
                    ):
                        logger.info('Skip. id=%s', event_id)
                        continue

                # Construct new Google event from Facebook data
                event: Event = {
                    'id': event_id,
                    'status': 'confirmed',
                    'summary': src_event.name,
                    'start': {'dateTime': src_event.begin.for_json()},
                    'source': {'title': 'Facebook event', 'url': src_event.url},
                }

                if src_event.end:
                    event['end'] = {'dateTime': src_event.end.for_json()}
                if src_event.description:
                    event['description'] = src_event.description
                if src_event.location:
                    event['location'] = src_event.location

                logger.debug('Request body. id=%s %r', event_id, J(event))

                # If event is existent, update. Otherwise, create new event.
                try:
                    if dst_event is None:
                        logger.info('Insert. id=%s', event_id)
                        event = service.events().insert(calendarId=config.calendar_id, body=event).execute()
                    else:
                        logger.info('Update. id=%s', event_id)
                        event = service.events().update(calendarId=config.calendar_id, eventId=event_id, body=event).execute()

                    logger.debug('Response. id=%s %r', event_id, J(event))
                except HttpError:
                    logger.exception('Error! id=%s', event_id)

        # Delete all Google events that aren't on Facebook
        for event_id in events_to_delete:
            logger.info('Delete. id=%s', event_id)
            try:
                service.events().delete(calendarId=config.calendar_id, eventId=event_id).execute()
            except HttpError:
                logger.exception('Error! id=%s', event_id)
    except Exception:
        logger.exception('General failure!')

    logger.info('Finished.')


COMMANDS: dict[str, Callable[['CalendarResource', Config], None]] = {
    'calendars': print_calendars,
    'events': print_events,
    'update-times': print_update_times,
    'sync': sync_calendar,
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--ics-url')
    p.add_argument('--calendar-id')
    p.add_argument('--credentials', type=pathlib.Path, default=platformdirs.user_config_path(__spec__.name, False) / 'credentials.json')
    p.add_argument('--storage-dir', type=pathlib.Path, default=platformdirs.user_config_path(__spec__.name, False))
    p.add_argument('--log-level', type=lambda s: logging.getLevelNamesMapping()[s.upper()], default=logging.INFO)
    p.add_argument('command', nargs='?', choices=['calendars', 'events', 'update-times', 'sync'], default='sync')
    args = p.parse_args()

    logging.basicConfig(level=args.log_level, format='%(asctime)s:%(levelname)s:%(message)s')

    config = Config(args.ics_url, args.calendar_id)

    try:
        service = get_service_client(args.credentials, args.storage_dir)
    except Exception:
        logger.exception('Failed initializing API!')
        raise SystemExit(1) from None

    COMMANDS[args.command](service, config)


if __name__ == '__main__':
    main()
