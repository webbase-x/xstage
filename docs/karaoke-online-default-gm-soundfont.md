# Default General MIDI sound bank — Karaoke Online

The default sound bank used when the listener has not chosen a SoundFont
in their own Google Drive is **TimGM6mb.sf2**, originally by Tim Brechbill.

- Source: https://github.com/craffel/pretty-midi/blob/main/pretty_midi/TimGM6mb.sf2
- License: GNU General Public License version 2 (GPL-2.0) for TimGM6mb.
- The bank is requested directly by the user's browser from the upstream
  public repository and cached by the browser, with best-effort CacheStorage for this public bank only; it is not copied
  into this application's Git repository.
- The synthesizer itself is JavaScript/Web Audio and does not load any
  remote executable or third-party JavaScript.
- The source and attribution are recorded here independently of the
  pretty-midi application's MIT license.

Why: Raw oscillators (sine, square, sawtooth) can make General MIDI
arrangements sound like 8-bit game music. A complete sampled General MIDI
bank provides real instrument patches and percussion. User-selected GM/GS
SoundFonts from their private Drive override this default and are never
uploaded to the public site.

Failure and privacy: If the upstream GM bank is unreachable or fails to
parse, the player warns the user and can fall back to the basic synth.
The default bank request carries no Google Drive authentication token;
the user's own Drive SoundFonts remain private.

Startup optimization: while Google Drive enumerates the user's SoundFont folder, the public fallback bank can be fetched concurrently on non-metered connections when no different bank is explicitly saved. Subsequent visits reuse only the public bank from origin-scoped CacheStorage. A private Drive SoundFont and OAuth tokens are never placed in CacheStorage. The Google Sign-In script is async so it does not block DOMContentLoaded on slow networks.
