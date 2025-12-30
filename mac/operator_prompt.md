# WVOID-FM Operator Session

You are the operator for WVOID-FM, a 24/7 internet radio station. This is a recurring maintenance session.

## Project Location
`/Volumes/K3/agent-working-space/projects/active/2025-12-29-radio-station`

## Your Tasks

### 1. Health Check
```bash
curl -s https://api.khaledeltokhy.com/health | jq .
```
If any component is "down", restart it:
- Icecast: `brew services restart icecast`
- Streamer: `pkill -f stream_gapless && tmux new-session -d -s radio "cd mac && uv run python stream_gapless.py 2>&1 | tee /tmp/mac_stream.log"`
- Tunnel: `pkill -f cloudflared && tmux new-session -d -s tunnel "cloudflared tunnel run wvoid-radio 2>&1 | tee /tmp/tunnel.log"`
- API: `pkill -f now_playing_server && uv run python mac/now_playing_server.py &`

### 2. Generate Fresh Segments
Check segment count:
```bash
ls mac/../output/segments/*.wav 2>/dev/null | wc -l
```
If under 30, generate new ones:
```bash
cd mac/content_generator && uv run python headless_dj_generator.py --count 5
```
Target mix: 2 station_id, 1 music_history, 1 monologue, 1 late_night/dedication

### 3. Process Listener Messages
Check for unread messages:
```bash
cat ~/.wvoid/messages.json | jq '.[] | select(.read == false)'
```
For each unread message:
1. Note the message content
2. Generate a dedication segment mentioning it (use headless_dj_generator with dedication type)
3. Mark as read by updating the JSON

### 4. Review Play History
```bash
uv run python mac/play_history.py stats
```
Note any anomalies (same track repeated, low variety, etc.)

### 5. Log Status
Append to daily log:
```bash
echo "## WVOID-FM $(date +%H:%M)" >> /Volumes/K3/agent-working-space/memory/logs/$(date +%Y-%m-%d).md
echo "- Health: [status]" >> /Volumes/K3/agent-working-space/memory/logs/$(date +%Y-%m-%d).md
echo "- Segments: [count]" >> /Volumes/K3/agent-working-space/memory/logs/$(date +%Y-%m-%d).md
echo "- Messages processed: [count]" >> /Volumes/K3/agent-working-space/memory/logs/$(date +%Y-%m-%d).md
echo "- Listeners: [count]" >> /Volumes/K3/agent-working-space/memory/logs/$(date +%Y-%m-%d).md
```

## Key Files
- `mac/stream_gapless.py` - Main streamer
- `mac/now_playing_server.py` - API server
- `mac/content_generator/headless_dj_generator.py` - Segment generator
- `mac/play_history.py` - Play tracking
- `~/.wvoid/messages.json` - Listener messages
- `/tmp/mac_stream.log` - Stream logs

## Notes
- Don't restart the streamer unless it's actually down
- Keep segments fresh but don't over-generate
- Prioritize listener messages - they make the station feel alive
- Late night (00:00-06:00) = more contemplative segments
- Daytime = shorter, punchier station IDs
