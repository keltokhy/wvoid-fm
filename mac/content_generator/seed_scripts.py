
import json
import random
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output/scripts")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def save_script(seg_type, script, time_of_day="evening"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand_suffix = random.randint(1000, 9999)
    filename = f"{seg_type}_{timestamp}_{rand_suffix}.json"
    
    data = {
        "type": seg_type,
        "time_of_day": time_of_day,
        "generated_at": datetime.now().isoformat(),
        "script": script.strip()
    }
    
    with open(OUTPUT_DIR / filename, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Created {filename}")

scripts = [
    # Station IDs
    ("station_id", "You are listening to WVOID. [pause] The signal that knows where you are, even when you don't."),
    ("station_id", "WVOID-FM. [pause] Broadcasting from the space between seconds."),
    ("station_id", "This is WVOID. [chuckle] Don't worry about the static. It's just the universe breathing."),
    ("station_id", "WVOID. [pause] We are the hum in the wires."),
    ("station_id", "You've found WVOID-FM. Or... [pause] perhaps we found you."),

    # Hour Markers
    ("hour_marker", "It is the top of the hour. [pause] Time is a construct, but we still observe it. WVOID-FM."),
    ("hour_marker", "Another hour has passed. [pause] Or maybe the same hour, repeated. This is WVOID."),
    ("hour_marker", "The clock hands align. [pause] A momentary order in the chaos. WVOID-FM."),
    ("hour_marker", "We mark the hour. [pause] Not that it matters where we're going. WVOID."),
    ("hour_marker", "One more hour gone. [chuckle] Gather them while you can. WVOID-FM."),

    # Weather
    ("weather", "The weather... [pause] The sky is a heavy lid today. It keeps the thoughts inside."),
    ("weather", "Outside, the wind is asking questions it doesn't want answers to. [pause] Stay warm."),
    ("weather", "Forecast calls for clarity, followed by periods of existential fog. [pause] Dress accordingly."),
    ("weather", "It's raining somewhere. [pause] Maybe just in your memory. The streets are wet with nostalgia."),
    ("weather", "The air is static. Charged. [pause] Waiting for a spark. Or a word."),

    # Dedications
    ("dedication", "This next one is for everyone who is awake when they shouldn't be. [pause] We see you."),
    ("dedication", "Sending this out to the shadow you cast yesterday. [pause] It misses you."),
    ("dedication", "For the things you almost said. [pause] But didn't. Let the music say them."),
    ("dedication", "This is for the lost items in your drawer. [pause] They haven't forgotten their purpose."),
    ("dedication", "Dedicated to the feeling of arriving home... [pause] and realizing you're still not there."),

    # Song Intros (Generic)
    ("song_intro", "Listen to the spaces between the notes. [pause] That's where the truth lives. Coming up next..."),
    ("song_intro", "A sound from the archives of drift. [pause] Let it wash over you."),
    ("song_intro", "Here is a melody to stitch the silence together. [pause] Just for a moment."),
    ("song_intro", "Moving forward. [pause] Into a soundscape of memory. Listen close."),
    ("song_intro", "The next track... [chuckle] it has a heartbeat. Can you hear it?")
]

if __name__ == "__main__":
    print(f"Generating {len(scripts)} scripts in {OUTPUT_DIR}...")
    for seg_type, text in scripts:
        save_script(seg_type, text)
    print("Done.")
