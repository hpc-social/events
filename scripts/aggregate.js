const fs = require('fs');
const ical = require('node-ical');
const axios = require('axios');

// --- CONFIGURATION ---
const FILES = {
    local: 'events.json',
    feeds: 'feeds.json',
    outputJson: 'combined.json',
    outputIcs: 'calendar.ics'
};

// --- HELPER: Fetch Open Graph Image ---
async function fetchOgImage(url) {
    if (!url) return null;
    try {
        // Short timeout to prevent hanging the build
        const res = await axios.get(url, { 
            timeout: 3000, 
            headers: { 
                'User-Agent': 'Mozilla/5.0 (compatible; HPC-Calendar-Bot/1.0)' 
            } 
        });
        
        // Simple regex to grab the og:image content
        const match = res.data.match(/<meta property="og:image" content="([^"]+)"/i);
        return match ? match[1] : null;
    } catch (e) {
        // Silent failure is acceptable for metadata fetching
        return null;
    }
}

// --- HELPER: Generate ICS File Content ---
function generateICS(events) {
    const formatDate = (date) => {
        if (!date) return '';
        // Format: YYYYMMDDTHHmmSSZ
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
        
        // Clean description for ICS (escape newlines)
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

// --- MAIN EXECUTION ---
async function run() {
    console.log("--- Starting Aggregator ---");
    let allEvents = [];

    // 1. Load Local Events
    try {
        if (fs.existsSync(FILES.local)) {
            const local = JSON.parse(fs.readFileSync(FILES.local, 'utf8'));
            // Ensure local events have the image structure
            const formattedLocal = local.map(e => ({
                ...e,
                // If you ever want to support manual image URLs in events.json, add them here
                image: e.image || null 
            }));
            allEvents = [...formattedLocal];
            console.log(`Loaded ${local.length} local events.`);
        }
    } catch (e) {
        console.warn(`Warning: Could not load ${FILES.local}`);
    }

    // 2. Load Feed List
    let feeds = [];
    try {
        if (fs.existsSync(FILES.feeds)) {
            feeds = JSON.parse(fs.readFileSync(FILES.feeds, 'utf8'));
        }
    } catch (e) {
        console.warn(`Warning: Could not load ${FILES.feeds}`);
    }

    // 3. Process External Feeds
    for (const url of feeds) {
        try {
            console.log(`Fetching feed: ${url}`);
            const res = await axios.get(url);
            const data = ical.parseICS(res.data);
            
            let count = 0;
            for (let k in data) {
                const ev = data[k];
                if (ev.type === 'VEVENT') {
                    // Try to fetch image if URL exists
                    let image = null;
                    if (ev.url) {
                        image = await fetchOgImage(ev.url);
                    }

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
                    count++;
                }
            }
            console.log(`  -> Processed ${count} events.`);
        } catch (e) {
            console.error(`  -> Error fetching feed: ${e.message}`);
        }
    }

    // 4. Save combined.json
    console.log(`Writing ${allEvents.length} total events to ${FILES.outputJson}...`);
    fs.writeFileSync(FILES.outputJson, JSON.stringify(allEvents, null, 2));

    // 5. Generate and Save calendar.ics
    console.log(`Generating ${FILES.outputIcs}...`);
    const icsContent = generateICS(allEvents);
    fs.writeFileSync(FILES.outputIcs, icsContent);

    console.log("--- Done ---");
}

run();
