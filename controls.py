"""
controls.py — physical input, abstracted away from the rest of the program.

WHY THIS FILE EXISTS
--------------------
The radio needs to know four things: which source is selected, whether Casey
is switched on, when a transport button is pressed, and when the tuning knob
moves. It does NOT need to know that those facts come from GPIO pin 16, or
from a keypress, or from a web request.

So this module defines an *interface* — a shape that any input source must
fit — and then provides two implementations of it. The radio talks to the
interface and never learns which one it got.

This is worth internalising, because it pays off three separate ways here:

  1. You can write and test the whole radio before your switches arrive.
  2. When the panel is built, nothing in radio.py changes.
  3. If you later add a phone app or an IR remote, it is a third backend,
     not a rewrite.

The general principle is called dependency inversion: high-level logic
should depend on an abstraction, not on a specific low-level detail.

LEVEL vs EDGE
-------------
Two fundamentally different kinds of input appear here.

A TOGGLE has a *level*. It is up or it is down, and it stays that way.
You ask it "what are you right now?" — source_is_bluetooth().

A BUTTON has an *edge*. It has no meaningful resting state; what matters is
the instant it transitions. You do not ask a button anything, it tells you —
on_next().

Getting this distinction wrong is a classic bug. If you poll a button you
miss presses between polls, or register one press many times. If you treat a
toggle as an event you lose track of its state after a restart. Match the
mechanism to the physics.
"""

import logging
import threading

import config

log = logging.getLogger("casey.controls")


class Controls:
    """
    The interface. Every backend provides these.

    Event hooks are plain attributes. The radio assigns functions to them;
    the backend calls them when something happens. Assigning None (the
    default) means the event is ignored, so the radio only has to wire up
    the events it cares about.
    """

    def __init__(self):
        self.on_next   = None    # ()      transport
        self.on_prev   = None    # ()
        self.on_pause  = None    # ()
        self.on_tune   = None    # (delta) encoder rotated, +1 or -1
        self.on_select = None    # ()      encoder pressed

    # --- levels -----------------------------------------------------------
    def source_is_bluetooth(self):
        raise NotImplementedError

    def casey_enabled(self):
        raise NotImplementedError

    # --- lifecycle --------------------------------------------------------
    def start(self):
        pass

    def stop(self):
        pass

    # --- internal ---------------------------------------------------------
    def _fire(self, name, *args):
        """
        Call a hook if one is set, and never let a handler exception kill
        the input thread.

        This matters more than it looks. GPIO callbacks run on a thread
        owned by the gpiozero library. If a handler raises, that thread can
        die silently and your buttons stop working with no error on screen —
        one of the more baffling failure modes on a Pi.
        """
        fn = getattr(self, name, None)
        if fn is None:
            return
        try:
            fn(*args)
        except Exception:
            log.exception("handler %s failed", name)


# ---------------------------------------------------------------------------
# Hardware backend
# ---------------------------------------------------------------------------

class GPIOControls(Controls):
    """
    Real switches on the 40-pin header.

    WIRING
    ------
    Every input here uses the same pattern: one leg of the switch goes to a
    GPIO pin, the other to ground.

    The pin is configured with an internal pull-up resistor, which weakly
    holds it at 3.3 V when nothing else is driving it. Closing the switch
    connects the pin to ground and yanks it to 0 V.

        released / open   -> HIGH
        pressed  / closed -> LOW

    Without the pull-up the pin would be "floating": not connected to
    anything definite, picking up electrical noise from the air and reading
    randomly. The pull-up gives it a defined resting state. It is weak
    enough (around 50 kOhm) that the switch easily overrides it.

    gpiozero's Button class assumes exactly this arrangement and inverts the
    logic for you, so `is_pressed` is True when the pin is LOW.
    """

    def __init__(self):
        super().__init__()
        from gpiozero import Button, RotaryEncoder   # imported late, see make_controls

        # Toggles. We read these as levels, so we keep the objects and query
        # them; we do not attach events.
        self._source = Button(config.PIN_SOURCE, pull_up=True,
                              bounce_time=config.BOUNCE_TOGGLE)
        self._casey  = Button(config.PIN_CASEY, pull_up=True,
                              bounce_time=config.BOUNCE_TOGGLE)

        # Transport. These are edges, so we attach handlers.
        self._prev  = Button(config.PIN_PREV,  pull_up=True,
                             bounce_time=config.BOUNCE_BUTTON)
        self._pause = Button(config.PIN_PAUSE, pull_up=True,
                             bounce_time=config.BOUNCE_BUTTON)
        self._next  = Button(config.PIN_NEXT,  pull_up=True,
                             bounce_time=config.BOUNCE_BUTTON)

        self._prev.when_pressed  = lambda: self._fire("on_prev")
        self._pause.when_pressed = lambda: self._fire("on_pause")
        self._next.when_pressed  = lambda: self._fire("on_next")

        # The encoder. A rotary encoder is two switches offset from each
        # other, so the ORDER in which A and B change tells you which way it
        # turned. That is called quadrature encoding. gpiozero decodes it and
        # hands us clean direction events instead of raw edges.
        #
        # max_steps=0 means "do not clamp the count" — we only care about
        # direction, and we track position ourselves.
        self._enc = RotaryEncoder(config.PIN_ENC_A, config.PIN_ENC_B,
                                  max_steps=0, wrap=False)
        self._enc.when_rotated_clockwise         = lambda: self._fire("on_tune", +1)
        self._enc.when_rotated_counter_clockwise = lambda: self._fire("on_tune", -1)

        self._enc_sw = Button(config.PIN_ENC_SW, pull_up=True,
                              bounce_time=config.BOUNCE_BUTTON)
        self._enc_sw.when_pressed = lambda: self._fire("on_select")

        log.info("GPIO controls ready")

    def source_is_bluetooth(self):
        # Switch closed (pin pulled to ground) selects Bluetooth.
        return self._source.is_pressed

    def casey_enabled(self):
        return self._casey.is_pressed

    def stop(self):
        # gpiozero devices release their pins when garbage collected, which
        # is why the radio must hold a reference to this object for its whole
        # life. Closing explicitly is tidier.
        for dev in (self._source, self._casey, self._prev,
                    self._pause, self._next, self._enc, self._enc_sw):
            try:
                dev.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Keyboard backend
# ---------------------------------------------------------------------------

class KeyboardControls(Controls):
    """
    Stand-in for the panel, so you can run the radio before the hardware
    exists. Reads lines from the terminal on a background thread.

    Deliberately simple: no raw terminal mode, no curses. You type a letter
    and press Enter. It is not a nice interface, but it is not meant to be —
    it is a test harness, and every hour spent polishing a test harness is an
    hour not spent on the thing being tested.
    """

    KEYS = """
      n  next          p  previous        space  pause
      ,  tune down     .  tune up         s      select playlist
      b  toggle Bluetooth / library
      c  toggle Casey on / off
      q  quit
    """

    def __init__(self):
        super().__init__()
        self._bluetooth = False
        self._casey     = True
        self._stop      = threading.Event()
        self._thread    = None

    def start(self):
        print("Keyboard controls active:")
        print(self.KEYS)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                line = input().strip().lower()
            except EOFError:
                break

            if   line == "n":     self._fire("on_next")
            elif line == "p":     self._fire("on_prev")
            elif line in ("", " "): self._fire("on_pause")
            elif line == ",":     self._fire("on_tune", -1)
            elif line == ".":     self._fire("on_tune", +1)
            elif line == "s":     self._fire("on_select")
            elif line == "b":
                self._bluetooth = not self._bluetooth
                print(f"  SOURCE -> {'bluetooth' if self._bluetooth else 'library'}")
            elif line == "c":
                self._casey = not self._casey
                print(f"  CASEY  -> {'on' if self._casey else 'off'}")
            elif line == "q":
                self._fire("on_quit")

    def source_is_bluetooth(self):
        return self._bluetooth

    def casey_enabled(self):
        return self._casey

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_controls():
    """
    Pick a backend.

    Note that GPIOControls is imported inside a try block rather than at the
    top of the file. If gpiozero were imported at module level, this whole
    file would fail to load on your Mac — and then you could not test
    anything at all. Import the platform-specific thing lazily, at the point
    where you actually need it.
    """
    want = config.CONTROLS_BACKEND

    if want == "keyboard":
        return KeyboardControls()

    if want in ("auto", "gpio"):
        try:
            return GPIOControls()
        except Exception as e:
            if want == "gpio":
                raise
            log.info("GPIO unavailable (%s) — using keyboard", e)

    return KeyboardControls()
