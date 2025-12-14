const fs = require('fs');
const ical = require('node-ical');
const axios = require('axios');

// --- CONFIGURATION: Updated for docs/data structure ---
const FILES = {
    local: 'docs/data/events.json',
    feeds: 'docs/data/feeds.json',
    outputJson: 'docs/data/combined.json',
    outputIcs: 'docs/data/calendar.ics'
};

// --- HELPER: Fetch Open Graph Image ---
async function fetchOgImage(url) {
    if (!url) return null;
    try {
        const res = await axios.get(url, { 
            timeout: 3000, 
            headers: { 'User-Agent': 'Mozilla/5.0 (compatible; HPC-Calendar-Bot/1.0)' } 
        });
        const match = res.data.match(/<meta property="og:image" content="([^"]+)"/i);
        return match ? match[1] : null;
    } catch (e) { return null; }
}

// --- HELPER: Generate ICS ---
function generateICS(events) {
    const formatDate = (date) => {
        if (!date) return '';
        return new Date(date).toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
    };

    let lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//HPC Social//Community Calendar//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH'
    ];

    events.forEach(e => {
        lines.push('BEGIN:VEVENT');
        lines.push(`UID:${e.id}`);
        lines.push(`DTSTAMP:${formatDate(new Date())}`);
        lines.push(`DTSTART:${formatDate(e.start)}`);
        if (e.end) lines.push(`DTEND:${formatDate(e.end)}`);
        lines.push(`SUMMARY:${e.title}`);
        const desc = (e.extendedProps?.description || e.description || '').replace(/\n/g, '\\n');
        if (desc) lines.push(`DESCRIPTION:${desc}`);
        const loc = e.extendedProps?.location || e.location || '';
        if (loc) lines.push(`LOCATION:${loc}`);
        if (e.url) lines.push(`URL:${e.url}`);
        lines.push('END:VEVENT');
    });

    lines.push('END:VCALENDAR');
    return lines.join('\r\n');
}

// --- MAIN ---
async function run() {
    console.log("--- Starting Aggregator ---");
    let allEvents = [];

    // 1. Load Local
    try {
        if (fs.existsSync(FILES.local)) {
            const local = JSON.parse(fs.readFileSync(FILES.local, 'utf8'));
            const formattedLocal = local.map(e => ({ ...e, image: e.image || null }));
            allEvents = [...formattedLocal];
            console.log(`Loaded ${local.length} local events.`);
        }
    } catch (e) { console.warn(`Warning: Could not load ${FILES.local}`); }

    // 2. Load Feeds
    let feeds = [];
    try {
        if (fs.existsSync(FILES.feeds)) {
            feeds = JSON.parse(fs.readFileSync(FILES.feeds, 'utf8'));
        }
    } catch (e) { console.warn(`Warning: Could not load ${FILES.feeds}`); }

    // 3. Process External
    for (const url of feeds) {
        try {
            console.log(`Fetching feed: ${url}`);
            const res = await axios.get(url);
            const data = ical.parseICS(res.data);
            
            for (let k in data) {
                const ev = data[k];
                if (ev.type === 'VEVENT') {
                    let image = null;
                    if (ev.url) image = await fetchOgImage(ev.url);

                    allEvents.push({
                        id: ev.uid || Math.random().toString(36).substr(2, 9),
                        title: ev.summary || 'Untitled Event',
                        start: ev.start,
                        end: ev.end,
                        url: ev.url || '',
                        image: image,
                        extendedProps: { 
                            category: 'External', 
                            location: ev.location || '', 
                            description: ev.description || '' 
                        }
                    });
                }
            }
        } catch (e) { console.error(`Error fetching feed: ${e.message}`); }
    }

    // 4. Save Outputs
    fs.writeFileSync(FILES.outputJson, JSON.stringify(allEvents, null, 2));
    const icsContent = generateICS(allEvents);
    fs.writeFileSync(FILES.outputIcs, icsContent);
    console.log("--- Done ---");
}

run();
