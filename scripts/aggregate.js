const fs = require('fs');
const ical = require('node-ical');
const axios = require('axios');

// --- CONFIGURATION ---
const FILES = {
    // We now read AND write to the same file
    data: 'docs/data/events.json',
    feeds: 'docs/data/feeds.json',
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
    
    // 1. Load Existing Data
    let existingEvents = [];
    try {
        if (fs.existsSync(FILES.data)) {
            existingEvents = JSON.parse(fs.readFileSync(FILES.data, 'utf8'));
        }
    } catch (e) { console.warn(`Warning: Could not load ${FILES.data}`); }

    // 2. Filter out old External events
    // We keep events that DO NOT have the 'isFeed' flag.
    // This preserves manual events.
    let manualEvents = existingEvents.filter(e => !e.extendedProps?.isFeed);
    console.log(`Preserving ${manualEvents.length} manual events.`);

    // 3. Load Feeds List
    let feeds = [];
    try {
        if (fs.existsSync(FILES.feeds)) {
            feeds = JSON.parse(fs.readFileSync(FILES.feeds, 'utf8'));
        }
    } catch (e) { console.warn(`Warning: Could not load ${FILES.feeds}`); }

    // 4. Process External Feeds
    let newFeedEvents = [];
    
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

                    newFeedEvents.push({
                        id: ev.uid || Math.random().toString(36).substr(2, 9),
                        title: ev.summary || 'Untitled Event',
                        start: ev.start,
                        end: ev.end,
                        url: ev.url || '',
                        image: image,
                        // We mark these as Feed events so we can replace them next time
                        extendedProps: { 
                            isFeed: true, // <--- CRITICAL FLAG
                            category: 'External', 
                            location: ev.location || '', 
                            description: ev.description || '' 
                        }
                    });
                }
            }
        } catch (e) { console.error(`Error fetching feed: ${e.message}`); }
    }

    // 5. Merge Manual + New Feed Events
    const finalEvents = [...manualEvents, ...newFeedEvents];

    // 6. Write back to Single Source of Truth
    console.log(`Writing ${finalEvents.length} total events to ${FILES.data}...`);
    fs.writeFileSync(FILES.data, JSON.stringify(finalEvents, null, 2));

    // 7. Generate ICS for subscribers
    const icsContent = generateICS(finalEvents);
    fs.writeFileSync(FILES.outputIcs, icsContent);
    
    console.log("--- Done ---");
}

run();
