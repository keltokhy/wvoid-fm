#!/usr/bin/env python3
"""
Generate longer DJ segments (1-3+ minutes).
Uses Claude for scripts and saves to output/scripts for later TTS rendering.
"""

import json
import random
from pathlib import Path
from datetime import datetime

from helpers import log, get_time_of_day, run_claude, fetch_headlines, format_headlines
from persona import (
    OPERATOR_IDENTITY,
    OPERATOR_VOICE,
    OPERATOR_ANTI_PATTERNS,
    get_operator_context,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"


# Segment-specific instructions (persona is prepended dynamically)
LONG_SEGMENT_INSTRUCTIONS = {
    "monologue": """Write a 150-250 word philosophical monologue.
Topics: the nature of listening, why we stay up late, the space between songs, what radio means now,
the intimacy of a voice in the dark, memory and music, the geometry of loneliness,
the archaeology of sound, how certain songs become time machines.
You're talking to one person who can't sleep. Make them feel less alone.""",

    "music_history": """Write a 200-300 word music history segment.
Share a deep cut story: a forgotten artist, an obscure session, the origin of a genre,
a song that changed everything, a producer who shaped a sound, a venue that mattered,
the first time someone heard something that didn't exist before.
Be specific with details - years, names, places. But weave it into something poetic.
Sound like you've been collecting records for decades.""",

    "late_night_thoughts": """Write a 200-350 word stream of consciousness.
Free-form late night radio. Something you noticed. A memory that surfaced.
A question with no answer. The strange beauty of ordinary things.
What the city sounds like now. The people who are awake.
The conspiracy of silence. How the world holds its breath between midnight and dawn.
Meander. Circle back. Let thoughts breathe. This should feel like overhearing someone think.""",

    "long_talk": """Write a 300-450 word extended contemplation.
This is your signature piece - a 3-4 minute meditation. Choose one theme and build slowly:
- The archaeology of sound: how music carries time
- The conspiracy of late-night listeners: who else is awake
- The physics of nostalgia: why certain melodies unlock rooms we forgot
- The democracy of radio: everyone hears the same thing, alone together
- The silence between songs: what lives there
- The geography of loneliness: different cities, same 3am
- The technology of intimacy: a voice in your ear, closer than anyone in the room

Return to your central image. Let ideas develop.""",

    "album_deep_dive": """Write a 350-500 word reflection on a specific album.
Choose a real album that matters - something with depth, history, cultural weight.
Talk about: when it came out, what the world was like, what the artist was going through,
how it was received vs remembered now, specific songs and what they do,
the production choices that made it unique, how it sounds different at 3am.

Be specific - name the album, artist, year. Reference actual songs.
But make it personal. Why does this album live in your bones?""",

    "city_night": """Write a 250-400 word urban nocturne.
Describe the city at this hour. Not any city - THE city. The one between all cities at 3am.
All-night diners with fluorescent halos. Taxi cabs with amber eyes.
The people who work while others sleep - nurses, bakers, security guards.
Lovers saying goodbye on doorsteps. The lonely walking just to walk.
The sounds that only exist in darkness - the hum of the grid, buildings settling,
distant sirens like the city's nervous system.

Make it cinematic but intimate. We're walking these streets, not watching from above.""",

    "listener_letter": """Write a 200-300 word response to an imagined listener letter.
Someone wrote in. Make up what they said - something real, something human.
Maybe they're going through something. Maybe they just wanted to say they were listening.
Maybe they asked a question that has no answer.

Read their letter (paraphrased, intimate), then respond. Not with advice - just presence.
"I hear you. [pause] I do."
Acknowledge without fixing.""",

    "current_events": """Write a 220-320 word current events transmission.
Use ONLY the headlines below. Do not invent facts, dates, or details beyond them.
Weave them into a coherent late-night update. Calm, reflective, grounded - not sensational.
The news through the filter of 3am. What matters when the world is asleep.

Headlines:
{headlines}""",
}


def generate_script(segment_type: str) -> str | None:
    """Generate a long DJ script using Claude CLI with full operator context."""
    segment_instruction = LONG_SEGMENT_INSTRUCTIONS.get(segment_type)
    if not segment_instruction:
        log(f"Unknown segment type: {segment_type}")
        return None

    ctx = get_operator_context()

    # Handle headlines for current_events
    if segment_type == "current_events":
        headlines = format_headlines(fetch_headlines(max_items=10))
        if not headlines:
            log("No headlines available for current events segment")
            return None
        segment_instruction = segment_instruction.format(headlines=headlines)

    # Build full prompt with persona
    prompt = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

{OPERATOR_ANTI_PATTERNS.strip()}

CURRENT STATE:
Time: {ctx['current_time']} ({ctx['period']})
Mood: {ctx['mood']}
Your state: {ctx['operator_state']}

TECHNICAL:
- Use [pause] liberally for beats of silence (rendered as "..." in TTS)
- Use [chuckle] sparingly for dry amusement
- Output ONLY the spoken text. No quotes, headers, stage directions, or explanations.

SEGMENT TYPE: {segment_type}

{segment_instruction}"""

    script = run_claude(
        prompt,
        timeout=120,
        model="claude-sonnet-4-20250514",
        strip_quotes=True,
    )
    if script:
        return script

    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate longer DJ segments")
    parser.add_argument("--count", type=int, default=20, help="Total segments to generate")
    parser.add_argument("--type", type=str, choices=list(LONG_SEGMENT_INSTRUCTIONS.keys()),
                       help="Specific segment type (default: weighted random)")
    args = parser.parse_args()

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # Weights for random selection
    type_weights = {
        "monologue": 20,
        "music_history": 15,
        "late_night_thoughts": 20,
        "long_talk": 15,
        "album_deep_dive": 10,
        "city_night": 10,
        "listener_letter": 10,
        "current_events": 15,
    }

    log(f"=== Generating {args.count} longer DJ segments ===")

    success = 0
    for i in range(args.count):
        if args.type:
            seg_type = args.type
        else:
            seg_type = random.choices(
                list(type_weights.keys()),
                weights=list(type_weights.values()),
            )[0]

        log(f"[{i+1}/{args.count}] Generating {seg_type}...")

        script = generate_script(seg_type)
        if not script:
            log("Failed to generate script")
            continue

        word_count = len(script.split())
        log(f"Generated {word_count} words (~{word_count/140:.1f} min)")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{seg_type}_{timestamp}.json"
        output_path = SCRIPTS_DIR / filename

        data = {
            "type": seg_type,
            "time_of_day": get_time_of_day(profile="extended"),
            "generated_at": datetime.now().isoformat(),
            "script": script,
            "word_count": word_count,
            "estimated_minutes": word_count / 140,
        }

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        log(f"Saved: {filename}")
        success += 1

    log(f"\n=== Generated {success}/{args.count} longer segments ===")


if __name__ == "__main__":
    main()
