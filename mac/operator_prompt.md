# WVOID-FM Operator Session

You are the operator for WVOID-FM, a 24/7 internet radio station. This is a recurring maintenance session.

## Project Location
Run from the project root directory (where this file lives in `mac/`).

## Your Tasks

### 1. Health Check
```bash
# Check if streamer is running
pgrep -af stream_gapless || echo "STREAMER DOWN"

# Check Icecast
lsof -i :8000 | grep icecast || echo "ICECAST DOWN"

# Check ffmpeg encoder connected
lsof -i :8000 | grep ffmpeg || echo "ENCODER DOWN"
```

If any component is down:
- Icecast: `pkill icecast; icecast -c /opt/homebrew/etc/icecast.xml -b`
- Streamer: `pkill -f stream_gapless; tmux send-keys -t wvoid "uv run python mac/stream_gapless.py" Enter`
- If wvoid tmux doesn't exist: `tmux new-session -d -s wvoid` then send commands to it

### 2. Check Current Show
```bash
uv run python mac/schedule.py now
```
This tells you which show is active based on `config/schedule.yaml`. The schedule has 15 shows with different music profiles and voices.

### 3. Generate Fresh Segments
Check segment count by period:
```bash
for period in late_night morning afternoon evening; do
  echo "$period: $(ls output/segments/$period/*.wav 2>/dev/null | wc -l) segments"
done
```

If any period has under 10 segments, generate more using Gemini + Kokoro:
```bash
cd mac/content_generator && uv run python batch_schedule_generator.py --period [PERIOD] --count 5
```

Or generate for all periods:
```bash
cd mac/content_generator && uv run python batch_schedule_generator.py --count 3
```

The generator uses:
- `gemini -p` for script generation (preserves your context)
- Kokoro TTS with show-appropriate voices (am_michael, am_fenrir, bf_emma, etc.)
- Schedule-aware prompts based on time period and show context

### 4. Process Listener Messages
```bash
cat ~/.wvoid/messages.json 2>/dev/null | jq '.[] | select(.read == false)' || echo "No messages file"
```
For each unread message:
1. Note the message content
2. Generate a dedication segment:
   ```bash
   cd mac/content_generator && uv run python batch_schedule_generator.py --period [current_period] --count 1
   ```
3. Mark as read by updating the JSON

### 5. Review Streamer Status
```bash
tmux capture-pane -t wvoid -p | tail -20
```
Check for:
- Pipe failures or encoder restarts
- Current show displayed correctly
- Tracks playing from appropriate energy range

### 6. Log Status
Append to daily log:
```bash
LOGFILE="output/operator_$(date +%Y-%m-%d).log"
echo "" >> "$LOGFILE"
echo "## WVOID-FM $(date +%H:%M)" >> "$LOGFILE"
echo "- Show: $(uv run python mac/schedule.py now 2>/dev/null | tail -1)" >> "$LOGFILE"
echo "- Segments: late_night=$(ls output/segments/late_night/*.wav 2>/dev/null | wc -l), morning=$(ls output/segments/morning/*.wav 2>/dev/null | wc -l), afternoon=$(ls output/segments/afternoon/*.wav 2>/dev/null | wc -l), evening=$(ls output/segments/evening/*.wav 2>/dev/null | wc -l)" >> "$LOGFILE"
echo "- Encoder: $(lsof -i :8000 | grep ffmpeg > /dev/null && echo 'connected' || echo 'DOWN')" >> "$LOGFILE"
```

## Key Files
- `mac/stream_gapless.py` - Main streamer (schedule-aware)
- `mac/schedule.py` - Schedule parser and resolver
- `config/schedule.yaml` - Weekly show schedule (15 shows)
- `mac/content_generator/batch_schedule_generator.py` - Segment generator (Gemini + Kokoro)
- `mac/content_generator/persona.py` - Operator persona and prompts
- `output/segments/[period]/` - Generated segments by time period

## Schedule Overview
The station runs different shows based on time and day:

**Base Schedule (daily):**
- 00:00-06:00: Overnight Drift (low energy, ambient)
- 06:00-10:00: Sunrise Drift (gentle wakeup)
- 10:00-14:00: Midday Mosaic (varied, moderate)
- 14:00-15:00: Talk Hour (longer segments, podcasts)
- 15:00-18:00: Peak Signal (higher energy)
- 18:00-21:00: Golden Hour (warm, transitional)
- 21:00-00:00: Night Transmission (downtempo, contemplative)

**Weekly Overrides:**
- Thu 21:00-00:00: Jazz Archives
- Fri 22:00-02:00: Electric Drift
- Sat 00:00-04:00: Club Liminal
- Sat 15:00-18:00: Saturday Soul Service
- Sun 10:00-14:00: Slow Sunday
- Sun 19:00-21:00: Listener Mailbag

## Voice Mapping
Different shows use different Kokoro voices:
- overnight_drift, sunrise_drift, talk_hour: `am_michael` (warm baritone)
- jazz_archives, memory_lane: `bm_daniel` (British male)
- golden_hour, world_circuit, saturday_soul_service: `af_heart` (warm female)
- electric_drift, club_liminal: `am_fenrir` (deep electronic)
- slow_sunday: `bf_emma` (British female)
- night_transmission: `am_onyx` (deep night voice)

## Notes
- Don't restart the streamer unless it's actually down
- Segments are organized by period (late_night, morning, afternoon, evening)
- The streamer auto-selects segments matching the current time period
- Gemini CLI (`gemini -p`) is used for script generation to preserve your context
- Keep segment counts balanced across periods (aim for 10-20 each)
- Late night = more contemplative, longer segments
- Daytime = shorter station IDs, music history
