#!/usr/bin/env python3

# Retrieve new jobs from the online form and validate
# Update with new jobs
# Also check for expiration and remove these from the site
# Copyright @vsoch, 2020-2023

import os
import copy
import datetime
import requests
import yaml
import urllib
import json
import pytz
import sys
import icalendar
import uuid
import time
from dateutil.rrule import rrulestr, rruleset

here = os.path.dirname(os.path.abspath(__file__))

scanned_url_file = os.path.join(here, "scanned-urls.txt")
scanner_token = os.environ.get("SCANNER_KEY")

# Keep track of today so we don't add old events
now = datetime.datetime.utcnow()
now.replace(tzinfo=pytz.utc)
today = datetime.datetime.utcnow().replace(tzinfo=pytz.utc).date()


def load_scanned_urls():
    """
    Load previously scanned cache of safe URLs.
    Any unsafe urls will be removed from the sheet.
    """
    scanned_urls = set()

    # Ensure we read in previously scanned URLs to not waste API quota (5k/month)
    if os.path.exists(scanned_url_file):
        with open(scanned_url_file) as fd:
            scanned_urls = set([x.strip() for x in fd.read().split("\n") if x.strip()])
    return scanned_urls


scanned_urls = load_scanned_urls()


def save_scanned_urls():
    """
    Save updated scanned urls.
    """
    global scanned_urls

    print(f"Saving updated urls to {scanned_url_file}")
    with open(scanned_url_file, "w") as fd:
        for url in scanned_urls:
            fd.write(url + "\n")


def is_malicious_url(url):
    """
    Use spam detection api to look for malicious URLs.
    """
    global scanned_urls

    # We've scanned it, and it's not malicious
    if url in scanned_urls:
        print(f"{url} has been previously seen and marked safe.")
        return False

    encoded_url = urllib.parse.quote(url, safe="")
    api_url = "https://ipqualityscore.com/api/json/url/%s/" % scanner_token
    response = requests.get(api_url + encoded_url)
    if response.status_code != 200:
        sys.exit("Issue using IP quality score API.")

    result = response.json()
    print(f"New result for {url}:")
    print(json.dumps(result, indent=4))

    # We don't allow any of this!
    if (
        result["suspicious"]
        or result["phishing"]
        or result["malware"]
        or result["spamming"]
        or result["adult"]
    ):
        print(
            "This result is not safe - determined to be suspicious, phishing, malware, spamming, or adult."
        )
        return True

    # If we get here, add to our scanned_urls
    scanned_urls.add(url)
    return False


def get_filepath(filename):
    """
    load the jobs file.
    """
    filepath = os.path.join(os.path.dirname(here), "_data", filename)

    # Exit on error if we cannot find file
    if not os.path.exists(filepath):
        print("Cannot find %s" % filepath)

    return filepath


def read_file(filepath):
    """
    read in the jobs data.
    """
    with open(filepath, "r") as fd:
        data = yaml.load(fd.read(), Loader=yaml.SafeLoader)
    return data


def get_google_sheet():
    """
    Read tab separated values sheet with locations!
    """
    # A tsv download for just the worksheet with city, state
    sheet = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSAxuTnQhiCVDdiHJScy8KKNWo6pnmnI1WVGQpPJKAtiPUnHsqMX81FJIDAx7RL6i8c9vsNyUUTpbcv/pub?output=tsv"

    # Ensure the response is okay
    response = requests.get(sheet)
    if response.status_code != 200:
        print(
            "Error with getting sheet, response code %s: %s"
            % (response.status_code, response.reason)
        )
        sys.exit(1)

    # Split lines by all sorts of fugly carriage returns
    lines = response.text.split("\r\n")

    # Remove empty responses, header row, make all lowercase
    lines = [x.strip('"').strip() for x in lines[1:] if x.strip()]
    return lines


def parse_lines(lines):
    """
    Parse new jobs from lines
    """
    events = {}
    for line in lines:
        line = [x.strip() for x in line.split("\t")]
        posted = line[0].split(" ")[0].strip()
        title = line[1].replace('"', "'")
        description = line[2].replace('"', "'")
        url = line[3].strip()
        host = line[4].strip()
        location = line[5].strip().replace('"', "'")
        start_date_time = line[6].strip()
        end_date_time = line[7].strip()
        event_types = line[8].strip().split(",")
        time_zone = line[9].strip()

        # If we have a url and key, check if
        if url and scanner_token:
            if is_malicious_url(url):
                sys.exit(f"Malicious url {url} detected, cancelling update.")

        for event_type in event_types:
            event_type = event_type.strip()
            if event_type not in events:
                events[event_type] = []

            events[event_type].append(
                {
                    "posted": posted,
                    "title": title,
                    "description": description,
                    "host": host,
                    "url": url,
                    "location": location,
                    "start_date_time": start_date_time,
                    "end_date_time": end_date_time,
                    "timezone": time_zone,
                    "categories": ", ".join(event_types),
                }
            )

    return events


def event_uid(event):
    return str(event["DTSTART"]) + str(event["DTEND"])


class Calendar:
    def __init__(self, outdir, event_key, summary=None, start=None):
        self.outdir = outdir
        self.event_key = event_key

        # Newly added events
        self.new_events = {}

        # Existing events (if loaded)
        self._events = set()

        self.cal = icalendar.Calendar()
        self.cal["dtstart"] = start
        self.cal["summary"] = summary
        self.cal.add("prodid", "-//HPC Social//Calendar//")
        self.cal.add("x-wr-timezone", "UTC")
        self.cal.add("version", "2.0")
        self.cal.add("calscale", "GREGORIAN")
        self.cal.add("method", "PUBLISH")

    @property
    def new_events_count(self):
        return len(self.new_events)

    @property
    def total_events(self):
        return len(self.new_events) + len(self._events)

    @property
    def ical_file(self):
        return os.path.join(outdir, f"{self.event_key}.ical")

    def to_ical(self):
        """
        Export to icalendar
        """
        return self.cal.to_ical()

    def index(self):
        """
        Index events found in the calendar.
        """
        for event in self.cal.walk():
            if event.name == "VEVENT":
                self._events.add(event_uid(event))

    def add_event(self, event):
        """
        Add an event, but first determine if it already exists
        """
        summary = f"{event['title']} in {event['location']} hosted by {event['host']}"
        new_event = icalendar.Event()
        new_event.add("name", event["title"])
        new_event.add("description", event["description"])
        new_event.add("summary", summary)

        # Create event date and make timezone aware
        new_event.add(
            "dtstart", parse_date(event["start_date_time"], event["timezone"])
        )
        new_event.add("dtend", parse_date(event["end_date_time"], event["timezone"]))
        new_event.add(
            "dtstamp", datetime.datetime(2023, 1, 2, 0, 10, 0, tzinfo=pytz.utc)
        )
        new_event["location"] = icalendar.vText(event["location"])
        new_event["uid"] = str(uuid.uuid4())
        new_event.add("categories", event["categories"], encode=0)

        # Is this a new event?
        uid = event_uid(new_event)
        if uid not in self._events:
            self.new_events[uid] = event
        self.cal.add_component(new_event)

    def save(self):
        """
        Save back to file
        """
        with open(self.ical_file, "wb") as fd:
            fd.write(self.to_ical())


def parse_date(datestr, timezone):
    """
    Return a time aware datetime object from a date string and timezone.
    """
    # This makes it timezone aware
    dtime = datetime.datetime.strptime(datestr, "%m/%d/%Y %H:%M:%S")
    dtime = dtime.replace(tzinfo=pytz.timezone(timezone))
    # And hopefully converts to UTC?
    return datetime.datetime.utcfromtimestamp(time.mktime(dtime.timetuple()))


def update_events(outdir, metadata_file="calendar.yaml"):
    """
    clean out expired job postings from a file
    """
    # This has calendar metadata
    filepath = get_filepath(metadata_file)
    print("calendar metadata file is: %s" % filepath)
    meta = read_file(filepath)

    # Create dict of meta
    meta = {x["category"]: x for x in meta["calendars"]}

    # Google sheet with updated events
    lines = get_google_sheet()
    events = parse_lines(lines)

    # Keep category specific calendars, include one for all events
    all_events = Calendar(
        outdir, "all", summary=meta["all"]["summary"], start=meta["all"]["start"]
    )
    calendars = {"all": all_events}

    # Keep listing of unique parsed events
    parsed_events = {}

    # Find all categories of previous files (if exist)
    for event_type, eventlist in events.items():
        event_key = event_type.lower()

        # If the event type isn't in our lookup, add to general
        if event_key not in meta:
            event_key = "general"

        # Load or create a new calendar
        calendar = Calendar(
            outdir,
            event_key,
            summary=meta[event_key]["summary"],
            start=meta[event_key]["start"],
        )

        # Add events to event type and all events calendar
        for event in eventlist:
            print(f"Adding event {event['title']} to '{event_key}' calendar")
            calendar.add_event(event)
        calendars[event_key] = calendar
        parsed_events[json.dumps(event)] = event

    # Update "all" calendar just once!
    for _, event in parsed_events.items():
        print(f"Adding event {event['title']} to 'all' calendar")
        calendars["all"].add_event(event)

    # Update the calendar with associated ical feeds
    print("Updating from external ical feeds...")
    filepath = get_filepath("feeds.yaml")
    feeds = read_file(filepath)
    for feed in feeds:
        print(f"...updating from {feed['name']} calendar feed")
        calendars = update_from_feed(feed, calendars)

    # Use the "all" calendar to determine new events
    # TODO we can update social media, etc. with this list
    for name, calendar in calendars.items():
        print(
            f"Found {calendar.new_events_count} new events and a total of {calendar.total_events} for {calendar.event_key}"
        )
        calendar.save()
    save_scanned_urls()


def update_from_feed(feed, calendars):
    """
    Given a feed, update our calendars with the events in it.

    For now, we assume that events are not repeated (and don't check)
    """
    # Download the feed url (this should fail if there is an issue so a human looks at it)
    res = requests.get(feed["url"])
    if res.status_code != 200:
        sys.exit("Issue retrieving data for calendar feed {feed['url']}")

    # This is text of the ical feed
    cal = icalendar.Calendar.from_ical(res.text)

    # Add to feeds that are in categories
    for calname in calendars:
        if calname in feed["categories"] or calname == "all":
            print(f"Updating {calname} with {feed['slug']}")
            calendars[calname] = merge_calendars(feed, cal, calendars[calname])
    return calendars


def merge_calendars(feed, source, dest):
    """
    Given two calendars, merge source into dest.

    Modified from:
    https://gist.github.com/adamgreig/a5eada2934d19189c0f6
    """
    for event in source.walk("VEVENT"):
        end = event.get("dtend")

        # Only add events with endings!
        if end:
            if hasattr(end.dt, "date"):
                date = end.dt.date()
            else:
                date = end.dt

            if not (date >= today or "RRULE" in event):
                continue

            copied_event = icalendar.Event()
            for attr in event:
                if type(event[attr]) is list:
                    for element in event[attr]:
                        copied_event.add(attr, element)
                else:
                    copied_event.add(attr, event[attr])

            # Ensure we have the title, either just the feed title
            # or included with the current title
            title = (feed["slug"] + " " + copied_event.get("TITLE", "")).strip()
            copied_event.add("TITLE", title)

            # If it's an RRULE, it won't render and we need special logic
            if copied_event.get("RRULE") is not None:
                dates = get_rrules(copied_event)
                del copied_event["RRULE"]
                for dt in dates:
                    new_event = copy.deepcopy(copied_event)

                    # These will actually show up twice!
                    for key in ["DTSTART", "DTEND", "DTSTAMP"]:
                        if key in new_event:
                            del new_event[key]
                    new_event.add(
                        "DTSTART",
                        datetime.datetime(
                            dt.year,
                            dt.month,
                            dt.day,
                            dt.hour,
                            dt.minute,
                            dt.second,
                            tzinfo=pytz.utc,
                        ),
                    )
                    new_event.add(
                        "DTEND",
                        datetime.datetime(
                            dt.year,
                            dt.month,
                            dt.day,
                            dt.hour,
                            dt.minute,
                            dt.second,
                            tzinfo=pytz.utc,
                        ),
                    )
                    new_event.add(
                        "DTSTAMP",
                        datetime.datetime(
                            dt.year,
                            dt.month,
                            dt.day,
                            dt.hour,
                            dt.minute,
                            dt.second,
                            tzinfo=pytz.utc,
                        ),
                    )
                    dest.cal.add_component(new_event)

            # Otherwise add as normal event
            else:
                dest.cal.add_component(copied_event)
    return dest


def get_rrules(event):
    """
    Given an rrule event, derive dates for next year.

    Derived from:
    https://codereview.stackexchange.com/questions/137985/parse-rrule-icalendar-entries
    """
    rules_text = "\n".join(
        [line for line in event.content_lines() if line.startswith("RRULE")]
    )
    rules = rruleset()
    first_rule = rrulestr(rules_text, dtstart=event.get("dtstart").dt)

    # in some entries, tzinfo is missing
    if first_rule._until and first_rule._until.tzinfo is None:
        first_rule._until = first_rule._until.replace(tzinfo=UTC)
    rules.rrule(first_rule)
    exdates = event.get("exdate")

    if not isinstance(exdates, list):  # apparently this isn't a list when
        exdates = [exdates]  # there is only one EXDATE
    for exdate in exdates:
        try:
            rules.exdate(exdate.dts[0].dt)
        except AttributeError:  # sometimes there is a None entry here
            pass

    # Parse for next year why not
    now = datetime.datetime.now(pytz.UTC)
    in_one_year = now + datetime.timedelta(days=360)
    return rules.between(now, in_one_year)


def main(outdir):
    """
    a small helper to update the ical events files.
    """
    if not os.path.exists(outdir):
        sys.exit(f"{outdir} does not exist")
    update_events(outdir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Please include an output directory for ical files.")
    outdir = sys.argv[1]
    main(outdir)
