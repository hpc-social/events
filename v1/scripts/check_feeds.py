#!/usr/bin/env python3

# Retrieve new jobs from the online form and validate
# Update with new jobs
# Also check for expiration and remove these from the site
# Copyright @vsoch, 2020-2023

import os
import requests
import icalendar
import yaml
import json

here = os.path.dirname(os.path.abspath(__file__))


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


def main():
    """
    Validate the feeds in feeds.yaml
    """
    print("Checking validity of feeds.yaml...")
    feeds = read_file(get_filepath("feeds.yaml"))
    calendars = read_file(get_filepath("calendar.yaml"))
    categories = set([c["category"] for c in calendars["calendars"]])

    for feed in feeds:
        # Required fields
        for field in ["name", "slug", "url", "summary", "categories"]:
            if field not in feed:
                sys.exit(f"Feed {feed} is missing field {field}.")

        # No spaces allowed in slug!
        if " " in feed["slug"]:
            sys.exit(
                f"Found whitespace in slug {feed['slug']} - should be all upper with only dashes."
            )

        # Slug must be all uppercase
        if not feed["slug"].isupper():
            sys.exit(
                f"Found non-uppercase value in slug {feed['slug']} - should be all upper with only dashes."
            )

        # Categories must be a list
        if not isinstance(feed["categories"], list):
            sys.exit(
                f"Found non-list type of categories in {feed['name']}, this should be a list."
            )

        # Categories must be known!
        for category in feed["categories"]:
            if category not in categories:
                sys.exit(f"Feed {feed['name']} has unknown category {category}")

        # Validate that URL works!
        res = requests.get(feed["url"])
        if res.status_code != 200:
            sys.exit("Issue retrieving data for calendar feed {feed['url']}")

        # Validate that loads into icalendar
        try:
            cal = icalendar.Calendar.from_ical(res.text)
        except:
            sys.exit("Could not load feed {feed['name']} into ical format.")
    print("All feeds valid! ⭐️")


if __name__ == "__main__":
    main()
