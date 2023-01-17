# hpc.social Events

Welcome to the hpc.social events calendars! Here we provide ical feeds of events
that are relevant for the HPC social community. We first plan to add calendars,
and eventually automation to advertise new or updated events. 

[Add an Event](https://forms.gle/LZjUnDrLQ2YKmWni7)

We currently serve the following feeds for you to add to your calendar:

 - [All HPC Social Events](https://hpc.social/events/calendars/all.ical)
 - [Conferences](https://hpc.social/events/calendars/conference.ical)

And will be working on automation / web interfaces soon.s

## Development

Prepare a virtual environment, install dependencies, and run the script.

```bash
$ python -m venv env
$ source env/bin/activate
$ pip install -r scripts/requirements.txt
```

And target the pages/calendars directory:

```bash
$ python scripts/update_events.py ./calendars
```

<a rel="me" href="https://mast.hpc.social/@events">Mastodon</a>
