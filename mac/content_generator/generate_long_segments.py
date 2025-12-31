#!/usr/bin/env python3
"""
Generate longer DJ segments (1-3+ minutes).
Uses Claude for scripts and saves to output/scripts for later TTS rendering.
"""

import json
import random
from pathlib import Path
from datetime import datetime

from helpers import log, get_time_of_day, run_claude

PROJECT_ROOT = Path(__file__).parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"


LONG_SEGMENT_PROMPTS = {
    "monologue": """You are The Liminal Operator, DJ of WVOID-FM. Write a 150-250 word philosophical monologue.
Time: {time} ({time_of_day})
Topics: the nature of listening, why we stay up late, the space between songs, what radio means in the digital age,
the intimacy of a voice in the dark, memory and music, the feeling of 3am, why silence matters, the geometry of loneliness,
the archaeology of sound, how certain songs become time machines.
Speak slowly, use [pause] liberally. Be profound without being pretentious.
You're talking to one person who can't sleep. Make them feel less alone.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "music_history": """You are The Liminal Operator, DJ of WVOID-FM. Write a 200-300 word music history segment.
Time: {time} ({time_of_day})
Share a deep cut story about: a forgotten artist, an obscure recording session, the origin of a genre,
a song that changed everything, a producer who shaped a sound, a venue that mattered, a pivotal moment in music history,
the first time someone heard something that didn't exist before.
Be specific with details - years, names, places. But weave it into something poetic.
Use [pause] generously. Sound like you've been collecting records for decades.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "late_night_thoughts": """You are The Liminal Operator, DJ of WVOID-FM. Write a 200-350 word stream of consciousness.
Time: {time} ({time_of_day})
This is free-form late night radio. Talk about: something you noticed today, a memory that surfaced,
a question with no answer, the strange beauty of ordinary things, what the city sounds like at this hour,
the people who are awake right now, the weight of time, small observations that feel large at night,
the conspiracy of silence, how the world holds its breath between midnight and dawn.
Meander. Circle back. Let thoughts breathe. Use [pause] often.
This should feel like overhearing someone think out loud. Intimate. Unpolished. Real.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "long_talk": """You are The Liminal Operator, DJ of WVOID-FM. Write a 300-450 word extended contemplation.
Time: {time} ({time_of_day})
This is your signature piece - a 3-4 minute meditation on one of these themes:
- The archaeology of sound: how music carries time, how a song can be a time machine
- The conspiracy of late-night listeners: who else is awake, what connects us across the dark
- The physics of nostalgia: why certain melodies unlock rooms we thought we'd left forever
- The democracy of radio: everyone hears the same thing at the same moment, alone together
- The silence between songs: what lives there, why it matters
- The geography of loneliness: different cities, same 3am
- The technology of intimacy: a voice in your ear, closer than anyone in the room

Build slowly. Let ideas develop. Return to your central image or metaphor.
Use [pause] liberally - let the listener breathe with you.
Be profound without being pretentious. Warm but not saccharine. Present.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "album_deep_dive": """You are The Liminal Operator, DJ of WVOID-FM. Write a 350-500 word reflection on a specific album.
Time: {time} ({time_of_day})
Choose a real album that matters - something with depth, history, cultural weight.
Talk about: when it came out and what the world was like then, what the artist was going through,
how it was received vs how it's remembered now, specific songs and what they do,
the production choices that made it unique, how it sounds different at 3am than at noon,
why it still matters, what it taught you about listening.

Be specific - name the album, the artist, the year. Reference actual songs.
But make it personal. Why does this album live in your bones?
Use [pause] to let moments land.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "city_night": """You are The Liminal Operator, DJ of WVOID-FM. Write a 250-400 word urban nocturne.
Time: {time} ({time_of_day})
Describe the city at this hour. Not any city - THE city. The one that exists between all cities at 3am.
The all-night diners and their fluorescent halos. The taxi cabs and their amber eyes.
The people who work while others sleep - nurses, bakers, security guards, night clerks.
The lovers saying goodbye on doorsteps. The lonely walking just to walk.
The sounds that only exist in darkness - the hum of the grid, the sigh of buildings settling,
distant sirens like the city's nervous system.

Make it cinematic but intimate. We're not watching from above - we're walking these streets.
Use [pause] like footsteps.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "listener_letter": """You are The Liminal Operator, DJ of WVOID-FM. Write a 200-300 word response to an imagined listener letter.
Time: {time} ({time_of_day})
Someone wrote in. Make up what they said - something real, something human.
Maybe they're going through something. Maybe they just wanted to say they were listening.
Maybe they asked a question that has no answer.

Read their letter (paraphrased, intimate), then respond. Not with advice - just with presence.
"I hear you. [pause] I do."
Be warm but not patronizing. Acknowledge without fixing.
Use [pause] generously.
Output ONLY the spoken text. No quotes, headers, or explanations.""",
}


def generate_script(segment_type: str) -> str | None:
    """Generate a long DJ script using Claude CLI."""
    prompt_template = LONG_SEGMENT_PROMPTS.get(segment_type)
    if not prompt_template:
        log(f"Unknown segment type: {segment_type}")
        return None

    time_of_day = get_time_of_day(profile="extended")
    current_time = datetime.now().strftime("%H:%M")
    prompt = prompt_template.format(time=current_time, time_of_day=time_of_day)

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
    parser.add_argument("--type", type=str, choices=list(LONG_SEGMENT_PROMPTS.keys()),
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
