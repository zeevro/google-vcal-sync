# google-vcal-sync
A little utility to synchronize Facebook events into Google Calendar

The main file is "google_calendar.py". "ical.py" is just a helper library - it is needed because Facebook's idea of a well-formed vCal does not agree with the standard and hence bugs other vCal parsers out.

To make this work you have to:
- Create a calendar in you Google Calendar account for this to inject the events into (DO NOT use your main calendar, this will delete all of your events!!!!)
- Get your Facebook vCal link
- Run google_calendar.py interactively once to get the Google login tokens and stuff
- Set up a cron job to run google_calendar.py

Enjoy. :)
