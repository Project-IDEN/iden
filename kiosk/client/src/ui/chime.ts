/**
 * Tones for a person who cannot read the screen because their head is turned:
 * one note to start a movement, two rising ones once its frames are taken.
 *
 * Made from a tap on Start, because a browser keeps audio silent until the
 * page has been touched. A kiosk without a speaker simply stays quiet.
 */
export function createChime() {
  const context = new AudioContext();

  function note(frequency: number, at: number) {
    const start = context.currentTime + at;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.3, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.3);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + 0.35);
  }

  return {
    play(sound: "go" | "done") {
      if (sound === "go") note(523, 0);
      else {
        note(659, 0);
        note(880, 0.14);
      }
    },
    close: () => void context.close(),
  };
}
