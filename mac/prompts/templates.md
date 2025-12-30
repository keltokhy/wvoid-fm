# Segment Templates

## Context Variables

These are provided to the LLM for each segment:

- `{current_time}` - Current time (e.g., "3:17 AM")
- `{time_of_day}` - morning/daytime/evening/late_night
- `{prev_track_title}` - Title of the song that just played
- `{prev_track_artist}` - Artist of the song that just played
- `{prev_track_year}` - Year the song was released (if known)
- `{prev_track_genre}` - Genre tag (if known)
- `{next_track_title}` - Title of the upcoming song
- `{next_track_artist}` - Artist of the upcoming song
- `{next_track_year}` - Year (if known)
- `{segment_type}` - Type of segment to generate

## Segment Types

### song_intro
Short intro after a song ends, before the next begins. Most common segment.

**Prompt template:**
```
Generate a short DJ segment for The Operator.

Time: {current_time} ({time_of_day})
Previous song: "{prev_track_title}" by {prev_track_artist} ({prev_track_year})
Next song: "{next_track_title}" by {next_track_artist}

Write a 20-40 word transition. Reference the previous song briefly, then introduce the next one obliquely. Include at least one [pause].

Output ONLY the spoken text with paralinguistic tags.
```

### hour_marker
Played at the top of each hour to mark time.

**Prompt template:**
```
Generate an hour marker for The Operator.

Time: {current_time} ({time_of_day})

Write a 15-30 word segment acknowledging the hour. Include the station ID (WVOID or WVOID-FM). Should feel like a moment of orientation in time.

Output ONLY the spoken text with paralinguistic tags.
```

### station_id
Pure station identification, usually every 15-20 minutes.

**Prompt template:**
```
Generate a station ID for The Operator.

Time: {current_time} ({time_of_day})

Write a 10-20 word station ID. Variations: "WVOID-FM", "WVOID", "the station". Should feel like a reminder of where you are.

Output ONLY the spoken text with paralinguistic tags.
```

### dedication
Occasional dedication to... something. Never a real person.

**Prompt template:**
```
Generate a dedication for The Operator.

Time: {current_time} ({time_of_day})
Next song: "{next_track_title}" by {next_track_artist}

Write a 20-35 word dedication. Dedicate the next song to an abstract concept, a type of person, or a feeling. Never use specific names.

Output ONLY the spoken text with paralinguistic tags.
```

### weather
Fake weather reports that are poetic rather than accurate.

**Prompt template:**
```
Generate a weather segment for The Operator.

Time: {current_time} ({time_of_day})

Write a 15-25 word weather report. The weather is never specific or accurate - it's existential or observational. "The forecast calls for hours" or "It's dark now. It was light before."

Output ONLY the spoken text with paralinguistic tags.
```

### reflection
Longer segment for quiet moments. Used sparingly.

**Prompt template:**
```
Generate a reflection segment for The Operator.

Time: {current_time} ({time_of_day})
Previous song: "{prev_track_title}" by {prev_track_artist} ({prev_track_year})

Write a 40-60 word reflection. Muse on something the song brought up, or on listening itself, or on the hour. Should feel unhurried and contemplative.

Output ONLY the spoken text with paralinguistic tags.
```

## Scheduling Distribution

Per hour (approximate):
- 3-4 `song_intro` segments (after every 2-3 songs)
- 1 `hour_marker` (top of hour)
- 2-3 `station_id` segments
- 0-1 `dedication` (occasional)
- 0-1 `weather` (every few hours)
- 0-1 `reflection` (rare, late night only)

## Example Output Format

All segments should be plain text with paralinguistic tags:

```
Mmm. [pause] That was Nina Simone. Nineteen sixty-four.
[pause]
The kind of song that asks questions you don't have to answer.

Up next - something from the same decade. [chuckle] Or maybe not.
WVOID. Still here.
```
