# Tonight's build — Mac to wired Pi

Every command, what you should see, and what to do when it's wrong.

---

## What tonight realistically ends with

- Pi running, music on the SD card, playing through your Pyle speakers
- Real buttons, real toggles, real tuning knob — all working
- Roughly a dozen tracks that Casey actually introduces
- A batch job running overnight to narrate the rest

Intro generation takes a few minutes per track on a Pi. You are not narrating a whole library tonight. You are going to hear the machine work, with your hands on it.

Budget about **two and a half hours**, most of it waiting on downloads.

---

## Phase 0 — Put everything on the table

### Core

- [ ] Raspberry Pi 5
- [ ] Official 27 W USB-C power supply
- [ ] microSD card — **128 GB recommended**, see the note below
- [ ] SD card reader for your Mac
- [ ] Micro-HDMI to HDMI cable (the Pi 5 uses **micro**-HDMI, not full size)
- [ ] Monitor, USB keyboard, USB mouse
- [ ] Ethernet cable to your router
- [ ] USB flash drive, 32 GB or larger

**On card size.** The OS is about 8 GB, the speech model 1.9 GB, the language model 2 GB, and generated intros roughly 1 MB each. That's ~13 GB before a single song. Music runs about 7 MB per track, so 1,000 tracks is another 7 GB. A 64 GB card works for a curated library; 128 GB means you never think about it. If you outgrow it, `MUSIC_DIR` in `config.py` can point at a USB drive instead and nothing else changes.

### Audio chain

Your Pyle PL42BL are **passive** speakers — bare wires, no power of their own. They need an amplifier between the Pi and the drivers. A line-level output produces milliwatts; those drivers want watts. Connecting them straight to a DAC gives you a barely audible whisper.

- [ ] **USB audio dongle** — the Pi 5 has no headphone jack. Any USB-to-3.5 mm adapter, USB DAC, or USB headset works. Check your drawer first.
- [ ] **Class-D amplifier board** — a TPA3116D2 2-channel board, about $18
- [ ] **12 V 5 A power supply** with a 5.5 × 2.1 mm barrel plug, about $14
- [ ] **16 AWG speaker wire**, a few feet
- [ ] **3.5 mm cable** to get from DAC to amp — check what input your amp board has (3.5 mm jack, RCA, or bare screw terminals) and buy to match

**Why a TPA3116 at 12 V.** Car speakers are almost always 4 Ω. That board delivers roughly 2 × 20 W into 4 Ω on a 12 V supply, which is comfortably more than 4-inch drivers need for room volume, with headroom left so you're never driving it into clipping. You *can* run the board at 19–24 V for more power, but with these speakers you'd just be adding heat and distortion risk.

Check the impedance printed on your speaker magnets before you buy — if they're 8 Ω the same board is still fine, just quieter.

**Missing the amp tonight?** Everything else still works. Use your monitor's HDMI speakers to prove the system out, and add the amp when it arrives. Sound quality will be poor but nothing else changes.

### Controls

- [ ] Breadboard (half-size is fine)
- [ ] Male-to-female jumper wires
- [ ] 3 × pushbuttons — you mentioned having these
- [ ] 2 × SPDT slide switches — **substitute:** a bare jumper touched to ground works for testing
- [ ] 1 × KY-040 rotary encoder — **substitute:** skip it, playlists default to ALL TRACKS

Missing parts don't block you. Wire what you have.

---

## Phase 1 — Flash the SD card (on the Mac)

**1.1** Download Raspberry Pi Imager from `raspberrypi.com/software` and open it.

**1.2** Insert the SD card into your Mac.

**1.3** In Imager:
- **Choose Device** → Raspberry Pi 5
- **Choose OS** → Raspberry Pi OS (64-bit), the full desktop version, first in the list
- **Choose Storage** → your SD card. Check the size matches — picking the wrong drive erases it.

**1.4** Click **Next**. A dialog asks about OS customisation → **Edit Settings**.

**1.5** General tab:
- Hostname: `caseyradio`
- Username: `casey` (or whatever — **write it down**, you'll type it often)
- Password: something you'll remember
- Leave WiFi blank, you're on ethernet
- Skip locale settings

**1.6** Services tab: leave SSH off.

**1.7** Save → Yes → Yes. It writes for 5–10 minutes.

**1.8** Eject and remove the card when it finishes.

---

## Phase 2 — Load the USB drive (on the Mac)

Three things travel from the Mac: the voice references, the code, and some music.

**2.1** Plug in the USB drive and find its name:

```bash
ls /Volumes/
```

**2.2** Copy the voice files. These exist nowhere else — they're cut from audio you downloaded and separated. Replace `MYUSB` with your drive's actual name:

```bash
cd ~/casey_radio
mkdir -p /Volumes/MYUSB/casey
cp casey_ref.wav casey_ref2.wav casey_ref3.wav casey_ref4.wav \
   casey_ref5.wav casey_ref6.wav casey_ref7.wav \
   Modelfile casey_corpus.jsonl \
   /Volumes/MYUSB/casey/
```

**2.3** Download the six Python files from this conversation, then:

```bash
cp ~/Downloads/config.py ~/Downloads/controls.py ~/Downloads/audio.py \
   ~/Downloads/library.py ~/Downloads/radio.py ~/Downloads/generate_intros.py \
   /Volumes/MYUSB/casey/
```

**2.4** Now the music. **Copy a few hundred tracks tonight, not everything.** Moving tens of gigabytes eats an hour you'd rather spend building, and you need very little to prove the system works.

```bash
mkdir -p /Volumes/MYUSB/music
cp -R ~/Music/SOME_FOLDER /Volumes/MYUSB/music/
```

Folder structure doesn't matter — the scanner recurses into everything. Artist folders, decade folders, one flat pile, all fine.

**2.5** Check it all made it:

```bash
ls /Volumes/MYUSB/casey/
du -sh /Volumes/MYUSB/music/
```

Fifteen files in `casey/`, and a size you're happy to copy twice.

**2.6** Eject properly:

```bash
diskutil eject /Volumes/MYUSB
```

Yanking a USB drive without ejecting can corrupt what you just wrote.

---

## Phase 3 — First boot

**3.1** With the Pi **unplugged**, connect: SD card, micro-HDMI to monitor, keyboard, mouse, ethernet.

**3.2** Plug in power. A green light blinks, the monitor shows a rainbow square, and it boots to a desktop in about a minute.

**3.3** Open a terminal — the black icon in the top bar, or `Ctrl+Alt+T`.

**3.4** Update everything:

```bash
sudo apt update && sudo apt full-upgrade -y
```

Type your password when asked. It won't show characters as you type — that's normal, not a frozen terminal. Takes 5–15 minutes.

**3.5** Reboot:

```bash
sudo reboot
```

**3.6** Confirm what you've got:

```bash
uname -m
free -h
df -h /
python3 --version
```

Expect `aarch64`, your RAM, plenty of free space, and Python 3.11+. If `uname -m` says anything but `aarch64` you flashed the 32-bit OS — go back to Phase 1.

---

## Phase 4 — Copy everything onto the Pi

**4.1** Plug in the USB drive. A file manager may pop up; close it.

**4.2** Find the mount point:

```bash
ls /media/$USER/
```

**4.3** Copy the project files and the music into place:

```bash
mkdir -p ~/casey_radio ~/music
cp /media/$USER/*/casey/* ~/casey_radio/
cp -R /media/$USER/*/music/* ~/music/

ls ~/casey_radio/
find ~/music -type f | wc -l
```

You should see 15 files, and a count of the songs you copied.

**Why `~/music` specifically:** that's the default `MUSIC_DIR` in `config.py`. If you'd rather keep music elsewhere, edit that one line — nothing else in the code refers to the path.

---

## Phase 5 — Install the software

**5.1** System packages:

```bash
sudo apt install -y python3-venv python3-dev python3-pip ffmpeg \
    libportaudio2 portaudio19-dev libsndfile1 libatlas-base-dev git
```

**5.2** Create the Python environment:

```bash
cd ~/casey_radio
python3 -m venv venv
source venv/bin/activate
```

Your prompt now starts with `(venv)`. **Every new terminal needs `source ~/casey_radio/venv/bin/activate` again.** If a command dies with "ModuleNotFoundError," this is nearly always why.

**5.3** PyTorch:

```bash
pip install --upgrade pip
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

Several minutes — it's a big download.

**5.4** Everything else:

```bash
pip install coqui-tts sounddevice soundfile mutagen requests numpy gpiozero lgpio
```

**5.5** Check:

```bash
python -c "from TTS.api import TTS; print('TTS ok')"
python -c "import sounddevice; print('audio ok')"
python -c "from gpiozero import Button; print('gpio ok')"
```

Three "ok" lines. If TTS fails, paste the error — that's the install most likely to need help.

**5.6** Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable ollama
sudo systemctl start ollama
ollama pull llama3.2:3b
```

**5.7** Point your persona at the smaller model:

```bash
nano ~/casey_radio/Modelfile
```

Change the first line from `FROM llama3.1:8b` to:

```
FROM llama3.2:3b
```

`Ctrl+O`, Enter, `Ctrl+X` to save and exit.

```bash
cd ~/casey_radio
ollama create casey -f Modelfile
ollama run casey "Introduce Dreams by Fleetwood Mac."
```

You should get a Casey-style line. `/bye` to exit.

---

## Phase 6 — Build the audio chain

### 6.1 Wire the amplifier — with everything unplugged

```
USB DAC ──3.5mm──> Amp input
Amp LEFT  +/− ──16AWG──> Left speaker  +/−
Amp RIGHT +/− ──16AWG──> Right speaker +/−
12V PSU ──barrel──> Amp DC input
```

Four rules, each of which prevents a specific failure:

1. **Never power the amp from the Pi.** It pulls several amps at volume. The Pi browns out, and a brownout during an SD write corrupts the card. Separate supplies, always.
2. **Match polarity.** Speaker terminals are marked + and −; on car speakers the + terminal is usually the wider blade. One channel wired backwards still plays — it just cancels the bass in a way that's maddening to diagnose later.
3. **Connect speakers before powering the amp**, and never let the two output wires of a channel touch. Shorting a Class-D output can kill the board.
4. **Turn the amp's volume knob all the way down** before first power-on.

### 6.2 Tell the Pi to use the DAC

Power the Pi on, plug in the USB dongle, then:

```bash
aplay -l
```

```
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: ...
card 1: Device [USB Audio Device], device 0: USB Audio
```

Note the **card number** of your dongle — probably 1.

```bash
speaker-test -D plughw:1,0 -c 2 -t wav
```

Replace `1` with your card number. Bring the amp's volume up slowly. You should hear "front left, front right" — and they should come from the correct sides. `Ctrl+C` to stop.

Nothing? Try the other card number. Still nothing? Check `alsamixer` — arrow keys to raise, `M` to unmute, `Esc` to quit.

### 6.3 Make it the default

```bash
cat > ~/.asoundrc << 'EOF'
pcm.!default {
    type plug
    slave.pcm "hw:1,0"
}
ctl.!default {
    type hw
    card 1
}
EOF

speaker-test -c 2 -t wav
```

Change **both** `1`s to your card number. No `-D` flag this time. If you hear it, audio is done.

**Why this file matters:** without it, Python's `sounddevice` will probably grab HDMI. No error, no warning, no sound — a genuinely maddening failure mode because everything looks like it's working.

### 6.4 A note about the tuba bell

Leave the speakers on the bench tonight. When you do mount them, know that a speaker with an open back cancels its own bass — the rear wave meets the front wave and low frequencies disappear. The bell will project midrange beautifully and sound thin underneath.

The fix is to seal the driver into the bell so the back is enclosed, or build a small sealed chamber behind it. Worth planning for, but not tonight's problem.

---

## Phase 7 — Wire the breadboard

### Power off first

```bash
sudo shutdown -h now
```

Wait for the green light to stop, then unplug. **Never wire GPIO on a powered Pi.** One slip shorting a pin to 5 V kills the board permanently.

### 7.1 Find pin 1 — don't guess

Power on briefly and run:

```bash
pinout
```

It prints a labelled diagram of the actual header. Match it to the board in front of you, identify which end is pin 1, then shut down again.

**Odd pins (1, 3, 5…) are one row, even pins (2, 4, 6…) are the other.** Pin 1 and pin 2 sit side by side at the same end.

### 7.2 Ground rail first

One jumper from **physical pin 6** to the **negative (−) rail** of the breadboard. Everything that needs ground goes to that rail — all the Pi's GND pins are the same electrical point.

### 7.3 Three pushbuttons

A 6 mm tactile button has four legs but really only two contacts: the legs on each side are permanently joined, and pressing bridges the sides.

**Straddle the centre channel of the breadboard with each button.** That orientation is always correct — one side of the gap is one contact, the other side is the other.

Per button: one leg to the negative rail, the opposite leg to its GPIO pin.

| Button | Physical pin | GPIO |
|---|---|---|
| PREV | 11 | 17 |
| PAUSE | 13 | 27 |
| NEXT | 15 | 22 |

### 7.4 Two toggles

An SPDT slide switch has three legs.

- **Middle leg** → negative rail
- **One outer leg** → its GPIO pin
- **Third leg** → leave bare

| Toggle | Physical pin | GPIO |
|---|---|---|
| SOURCE (Bluetooth / library) | 36 | 16 |
| CASEY (narration on / off) | 38 | 20 |

**No slide switches tonight?** Leave those pins empty. Both read "open," which means library mode with Casey on — exactly what you want. To test by hand, touch a jumper between the GPIO pin and the ground rail.

### 7.5 Rotary encoder

| KY-040 pin | Physical pin | GPIO |
|---|---|---|
| GND | negative rail | — |
| + | 1 | 3.3 V |
| CLK | 29 | 5 |
| DT | 31 | 6 |
| SW | 33 | 13 |

**Don't have one?** Skip it. Playlists default to ALL TRACKS.

### 7.6 Check before powering up

Walk each wire with a finger from component to header, counting pins each time. Off-by-one is the most common wiring error and it's invisible until nothing works.

Confirm specifically: **nothing is connected to physical pins 2 or 4.** Those are 5 V, and 5 V into a GPIO pin damages the Pi.

Power back on.

---

## Phase 8 — Test the wiring alone

Prove the buttons work before involving the radio.

```bash
cd ~/casey_radio
source venv/bin/activate

cat > test_controls.py << 'EOF'
import logging, time
from controls import make_controls
logging.basicConfig(level=logging.INFO)

c = make_controls()
c.on_next   = lambda: print(">>> NEXT")
c.on_prev   = lambda: print(">>> PREV")
c.on_pause  = lambda: print(">>> PAUSE")
c.on_select = lambda: print(">>> SELECT")
c.on_tune   = lambda d: print(">>> TUNE", "+" if d > 0 else "-")
c.start()

print("Press buttons and turn the knob. Ctrl+C to stop.")
last = None
try:
    while True:
        state = (c.source_is_bluetooth(), c.casey_enabled())
        if state != last:
            print(f"    SOURCE={'bluetooth' if state[0] else 'library'}   "
                  f"CASEY={'on' if state[1] else 'off'}")
            last = state
        time.sleep(0.05)
except KeyboardInterrupt:
    c.stop()
EOF

CASEY_CONTROLS=gpio python test_controls.py
```

`CASEY_CONTROLS=gpio` forces hardware mode, so it errors loudly instead of quietly falling back and leaving you wondering why nothing responds.

| Problem | Cause |
|---|---|
| One button does nothing | That leg isn't connected, or you counted to the wrong pin |
| One button fires constantly | Shorted to ground — check the legs aren't bridged |
| One press prints twice | Raise `BOUNCE_BUTTON` in `config.py` from `0.08` to `0.15` |
| Encoder counts backwards | Swap the CLK and DT wires |
| gpiozero error on start | A pin in `config.py` doesn't match your wiring |

Don't move on until everything you wired responds correctly. A wiring fault and a software fault at the same time take four times as long as either alone.

---

## Phase 9 — Run the radio

```bash
cd ~/casey_radio
source venv/bin/activate
mkdir -p cache logs
CASEY_CONTROLS=gpio python radio.py
```

Expect:

```
music: /home/casey/music
scanned 312 playable tracks (4 skipped)
PLAYLIST ALL TRACKS — 312 tracks, 0/312 have intros
GPIO controls ready
==============================================
  CASEY RADIO — on air
==============================================
TRACK Fleetwood Mac — Dreams
```

Music plays. NEXT skips, PAUSE holds, PREV goes back. `Ctrl+C` to stop.

That's a working radio with physical controls. No narration yet — the cache is empty.

**"no music folder"** means `~/music` doesn't exist or is empty. Check with `find ~/music -type f | wc -l`.

**Skipped tracks** are files with no readable tags *and* a filename the scanner couldn't parse. A few is normal. Many means your files are named something like `track01.mp3` — rename them `Artist - Title.mp3` and they'll be picked up.

---

## Phase 10 — Hear Casey tonight

**10.1** Read before you listen. This writes intro text without loading the speech model, so it takes about a minute:

```bash
python generate_intros.py --dry-run --limit 15
```

Read them. The model will confidently invent facts about artists — that's how it works, not a bug you can fix. Decide whether the style is right before spending hours synthesising.

**10.2** Generate a dozen for real:

```bash
python generate_intros.py --limit 12
```

The first run downloads the XTTS model (~1.9 GB) and asks you to accept Coqui's licence — type `y`. Then it generates, printing a per-track time and an ETA.

**Note that per-track time.** Multiply by your library size — that's your overnight job.

**10.3** Run the radio again:

```bash
CASEY_CONTROLS=gpio python radio.py
```

Most tracks play straight through. When one of your twelve comes up, Casey introduces it.

**10.4** Test the CASEY toggle. During an intro, flip it off — or touch a jumper between pin 38 and ground. He stops mid-sentence within about 46 milliseconds. Flip it back and the next transition narrates again.

That's the feature you asked for, running on real hardware.

---

## Phase 11 — Set the overnight batch running

**11.1** Make some playlists:

```bash
nano ~/casey_radio/playlists.json
```

```json
{
  "playlists": [
    { "name": "ALL TRACKS", "match": {} },
    { "name": "70s AT40",   "match": { "year_range": [1970, 1979] } },
    { "name": "YACHT ROCK", "match": { "artists": ["Hall", "Steely Dan", "Toto", "Doobie"] } }
  ]
}
```

`Ctrl+O`, Enter, `Ctrl+X`.

**11.2** Start the batch and leave it:

```bash
python generate_intros.py
```

It saves after every single track, so an interruption costs one intro rather than the whole run. Leave the terminal open overnight.

---

## Tomorrow

- `git init` in `~/casey_radio` and commit before editing anything
- Copy the rest of your library across
- Wire the SOURCE toggle, pair a phone over Bluetooth
- Work out the speaker enclosure behind the bell

## Commands you'll use constantly

```bash
cd ~/casey_radio && source venv/bin/activate     # every new terminal
CASEY_CONTROLS=gpio python radio.py              # run it
tail -f ~/casey_radio/logs/casey.log             # watch what it's doing
pinout                                           # the header diagram
aplay -l                                         # list sound cards
find ~/music -type f | wc -l                     # how many songs it can see
```
