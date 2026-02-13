# Habit Tracker ePaper Display

A Raspberry Pi + Waveshare 7.5" e-paper habit tracker with a retro pixel-art aesthetic. It pulls your daily habits from a Notion database and renders them as a "Daily Quests" screen — updating within 30 seconds of any change.

```
╔═══════════════════════════════════════════════════════╗
║      ★ DAILY QUESTS ★         THU • JAN 30 • 2026    ║
╠═══════════════════════════════════════════════════════╣
║                                                       ║
║   💧  DRINK 4L WATER                        [ ✓ ]    ║
║   ♞   PLAY CHESS                            [   ]    ║
║   📝  WRITE NOTES                           [ ✓ ]    ║
║   🐕  DOG EXERCISE                          [ ✓ ]    ║
║   💪  EXERCISE                              [ ✓ ]    ║
║   📖  READ 1 PAGE                           [ ✓ ]    ║
║                                                       ║
╠═══════════════════════════════════════════════════════╣
║      QUEST PROGRESS  █████████████░░░  5/6 DONE      ║
║               ✦ CURRENT STREAK: 7 DAYS ✦             ║
╚═══════════════════════════════════════════════════════╝
```

## How It Works

1. A **systemd timer** polls every 30 seconds
2. Each poll makes a single lightweight API call to check the database's `last_edited_time` — if nothing changed, it exits immediately
3. When a change is detected, the script fetches your **Notion database** for today's habit data (and historical data for streaks/calendar)
4. It renders an 800x480 **1-bit image** using Pillow with the Press Start 2P pixel font, custom icons, a progress bar, streak counter, and optional calendar heatmap
5. The image is pushed to the **Waveshare e-paper display** over SPI, then the display is put to sleep to save power

When the calendar is enabled, the screen splits into two panels — a weekly heatmap on the left showing your completion history, and the habit list on the right.

## Hardware Requirements

- Raspberry Pi Zero 2W (or any Pi with GPIO)
- Waveshare 7.5" V2 ePaper Display (800x480)
- MicroSD card (8GB+)
- Power supply

## Notion Setup

1. Create a Notion integration at https://www.notion.so/my-integrations

2. **Tracking database** — one row per day with a column per habit:
   - A **Date** property (must be named exactly "Date")
   - A property for each habit (Checkbox, Number, or Select)

3. **Habits database** (optional but recommended) — defines which habits to show on the display:

   | Property | Type | Description |
   |---|---|---|
   | **Name** | Title | Must match the property name in your tracking database |
   | **Display** | Rich text | Name shown on the ePaper screen (e.g. "Drink 2L water") |
   | **Icon** | Rich text | Icon filename from `assets/icons/` without `.png` |
   | **Start date** | Date | When tracking began (leave empty if always tracked) |
   | **Deactivated** | Date | When the habit was retired (leave empty if still active) |
   | **Sort order** | Number | Controls display order (ascending) |

   This lets you add, rename, reorder, or retire habits entirely from Notion — no code changes needed. Deactivated habits still count toward historical streak and calendar calculations for days before their deactivation date.

4. Share **both** databases with your integration (database page > `...` > Connect to)
5. Copy the integration API key and both database IDs

### Supported Property Types

Each habit property in your tracking database can be one of:

| Type | Counted as complete when... |
|---|---|
| **Checkbox** | Checked |
| **Number** | Value > 0 |
| **Select** | Any value selected |

## Installation

### Flashing the SD Card

1. Download and open [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Choose **Raspberry Pi OS Lite** (no desktop environment needed — this runs headless)
3. Click the gear icon to open the configuration screen:
   - Set a hostname (e.g. `raspberrypi.local`)
   - **Enable SSH** and add your public SSH key for passwordless access
   - Configure your Wi-Fi credentials
4. Flash the SD card, insert it into the Pi, and power it on
5. Wait for it to boot and connect to your network, then SSH in:
   ```bash
   ssh pi@raspberrypi.local
   ```

### On Raspberry Pi

1. Install git (not included in Raspberry Pi OS Lite):
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   ```

2. Clone this repository:
   ```bash
   git clone https://github.com/robertcoopercode/habit-tracker-epaper.git
   cd habit-tracker-epaper
   ```

3. Run the setup script:
   ```bash
   sudo ./setup.sh
   ```
   This installs system dependencies (including `python3-lgpio` for GPIO access), enables SPI, creates a Python virtual environment with system site-packages, and sets up the systemd timer. The script is idempotent — safe to rerun after `git pull`.

4. Configure your Notion credentials (either copy from your dev machine or create manually):
   ```bash
   # Option A: copy from your Mac
   # (run on your Mac) scp config.yaml pi@raspberrypi.local:~/habit-tracker-epaper/

   # Option B: create from template
   cp config.example.yaml config.yaml
   nano config.yaml
   ```

5. Reboot (required on first setup to enable SPI):
   ```bash
   sudo reboot
   ```

6. Test with demo data (no Notion required):
   ```bash
   .venv/bin/python -m src.main --demo
   ```

7. Test with your Notion data:
   ```bash
   .venv/bin/python -m src.main --preview
   ```

8. Start the automatic timer:
   ```bash
   sudo systemctl start habit-tracker.timer
   ```

### Updating After Code Changes

```bash
cd ~/habit-tracker-epaper && git pull && sudo ./setup.sh --skip-apt
```

The `--skip-apt` flag skips `apt-get update` for faster reruns when only code has changed.

### Local Development (without a Pi)

You can develop and preview on any machine — the display driver falls back to a mock when Waveshare hardware isn't available.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Generate a preview PNG with demo data (no Notion needed)
python -m src.main --demo --preview

# Generate a preview with real Notion data (requires config.yaml)
python -m src.main --preview
```

## Configuration

Copy `config.example.yaml` to `config.yaml` and fill in your values:

```yaml
notion:
  api_key: "secret_xxx"           # Your Notion integration API key
  database_id: "xxx-xxx-xxx"      # Your tracking database ID
  habits_database_id: "xxx-xxx"   # Your habits metadata database ID

display:
  rotation: 0                      # 0, 90, 180, or 270 degrees

streak:
  enabled: true                    # Show streak counter

calendar:
  enabled: true                    # Show weekly calendar heatmap
  weeks: 12                        # Number of weeks to display
```

If you prefer not to use the Habits database, you can define habits directly in config.yaml instead (omit `habits_database_id`):

```yaml
habits:
  - name: "DRINK 4L WATER"        # Display name (shown on screen)
    notion_property: "Water"       # Notion property name (case-sensitive)
    icon: "water"                  # Icon filename in assets/icons/ (without .png)
  - name: "PLAY CHESS"
    notion_property: "Chess"
    icon: "chess"
```

## Usage

```bash
# Update the ePaper display (skips if no Notion changes)
python -m src.main

# Force update even if nothing changed
python -m src.main --force

# Generate preview PNG (for development)
python -m src.main --preview

# Use demo data (no Notion required)
python -m src.main --demo

# Combine flags
python -m src.main --demo --preview --output my_preview.png

# Verbose logging
python -m src.main --verbose
```

## Systemd Commands

```bash
# Check timer status
systemctl status habit-tracker.timer

# View recent logs
journalctl -u habit-tracker.service -n 20

# Manually trigger an update
sudo systemctl start habit-tracker.service

# Force a display refresh
cd ~/habit-tracker-epaper && .venv/bin/python -m src.main --force

# Stop automatic updates
sudo systemctl stop habit-tracker.timer

# Disable on boot
sudo systemctl disable habit-tracker.timer
```

## Project Structure

```
habit-tracker-epaper/
├── src/
│   ├── main.py              # Entry point and CLI
│   ├── config.py            # YAML config loader + validation
│   ├── notion_service.py    # Notion API integration + change detection
│   ├── renderer.py          # Pillow-based image rendering
│   └── display_driver.py    # Waveshare ePaper driver (with mock fallback)
├── lib/
│   └── waveshare_epd/       # Vendored Waveshare driver (epd7in5_V2 only)
├── assets/
│   ├── fonts/
│   │   └── PressStart2P.ttf # Pixel font (OFL licensed)
│   └── icons/               # 24x24 PNG habit icons
├── config.example.yaml      # Example configuration
├── requirements.txt         # Python dependencies
├── setup.sh                 # Raspberry Pi setup script (idempotent)
├── habit-tracker.service    # systemd service unit (oneshot)
├── habit-tracker.timer      # systemd timer (every 30s)
└── wait_for_pi.sh           # Utility to wait for Pi on the network
```

## Customization

### Adding Custom Icons

Place a 24x24 PNG icon in `assets/icons/` and reference it in your config. Icons are rendered in 1-bit black and white to match the e-paper display.

```yaml
habits:
  - name: "MEDITATE"
    notion_property: "Meditation"
    icon: "meditation"  # assets/icons/meditation.png
```

### Adjusting Poll Frequency

Edit `habit-tracker.timer` and change `OnUnitActiveSec`:

```ini
[Timer]
OnUnitActiveSec=1min  # default is 30s
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart habit-tracker.timer
```

## Troubleshooting

### Display not updating

1. Check SPI is enabled:
   ```bash
   ls /dev/spidev*
   ```
   If no devices appear, enable SPI via `sudo raspi-config` > Interface Options > SPI, then reboot.

2. Check wiring connections between the Pi and the display.

3. Check the service logs:
   ```bash
   journalctl -u habit-tracker.service -f
   ```

4. Force an update to rule out change detection:
   ```bash
   cd ~/habit-tracker-epaper && .venv/bin/python -m src.main --force --verbose
   ```

### Notion API errors

- Verify your API key is correct in `config.yaml`
- Make sure the database is shared with your integration
- Property names are **case-sensitive** — they must match your Notion database exactly

## Credits

- Font: [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) (OFL License)
- ePaper library: [Waveshare](https://github.com/waveshare/e-Paper)

## License

MIT
