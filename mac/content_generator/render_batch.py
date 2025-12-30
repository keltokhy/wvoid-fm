
import sys
import json
import time
from pathlib import Path

# Add current directory to path so we can import tts_renderer
sys.path.insert(0, str(Path(__file__).parent))

from tts_renderer import TTSRenderer

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "output" / "scripts"
SEGMENTS_DIR = Path(__file__).parent.parent.parent / "output" / "segments"

def main():
    SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    
    scripts = list(SCRIPTS_DIR.glob("*.json"))
    if not scripts:
        print("No scripts found in output/scripts")
        return

    print(f"Found {len(scripts)} scripts. Initializing renderer...")
    
    try:
        # Use existing voice reference if available
        voice_ref = Path(__file__).parent.parent / "voice_reference" / "operator_voice.wav"
        renderer = TTSRenderer(voice_reference=voice_ref if voice_ref.exists() else None)
        
        # Trigger load
        renderer.load()
    except Exception as e:
        print(f"Failed to initialize renderer: {e}")
        # Continue? No, we need renderer.
        # But wait, maybe the user doesn't have the TTS model installed?
        # tts_renderer.py imports from a relative path. If that path is missing, it will fail.
        return

    count = 0
    skipped = 0
    errors = 0

    for i, script_path in enumerate(scripts):
        # Determine output filename
        # script: name.json -> audio: name.wav
        audio_filename = script_path.stem + ".wav"
        output_path = SEGMENTS_DIR / audio_filename
        
        if output_path.exists():
            print(f"[{i+1}/{len(scripts)}] Skipping {script_path.name} (already exists)")
            skipped += 1
            continue
            
        try:
            with open(script_path, "r") as f:
                data = json.load(f)
            
            script_text = data.get("script", "")
            if not script_text:
                print(f"[{i+1}/{len(scripts)}] Skipping empty script {script_path.name}")
                continue

            print(f"[{i+1}/{len(scripts)}] Rendering {script_path.name}...")
            renderer.render(script_text, output_path)
            count += 1
            
        except Exception as e:
            print(f"Error rendering {script_path.name}: {e}")
            errors += 1
            
    print(f"\nDone. Rendered {count}, Skipped {skipped}, Errors {errors}")

if __name__ == "__main__":
    main()
