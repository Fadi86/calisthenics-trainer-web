// Guided EMOM-style work/rest timer with audio cues (Web Audio API, no
// external sound files needed - generates a plain beep tone).

function beep(freq, durationMs) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    osc.start();
    osc.stop(ctx.currentTime + durationMs / 1000);
    setTimeout(() => ctx.close(), durationMs + 100);
  } catch (e) {
    // Web Audio unsupported or blocked - timer still works, just silent
    console.warn("Beep failed:", e);
  }
}

class GuidedTimer {
  constructor(workSeconds, restSeconds, totalSets, callbacks) {
    this.workSeconds = workSeconds;
    this.restSeconds = restSeconds;
    this.totalSets = totalSets;
    this.callbacks = callbacks || {};
    this.currentSet = 1;
    this.phase = "work"; // "work" | "rest"
    this.remaining = workSeconds;
    this.intervalId = null;
    this.paused = false;
  }

  start() {
    if (this.intervalId) return;
    this._announcePhase();
    this.intervalId = setInterval(() => this._tick(), 1000);
  }

  pause() {
    this.paused = !this.paused;
    if (this.callbacks.onPauseToggle) this.callbacks.onPauseToggle(this.paused);
  }

  skip() {
    this._advancePhase();
  }

  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  _tick() {
    if (this.paused) return;
    this.remaining -= 1;
    if (this.callbacks.onTick) this.callbacks.onTick(this.remaining, this.phase, this.currentSet);
    if (this.remaining <= 0) {
      this._advancePhase();
    }
  }

  _advancePhase() {
    if (this.phase === "work") {
      if (this.currentSet >= this.totalSets) {
        beep(880, 500); // completion beep, higher/longer
        this.stop();
        if (this.callbacks.onComplete) this.callbacks.onComplete();
        return;
      }
      this.phase = "rest";
      this.remaining = this.restSeconds;
      beep(440, 200); // work -> rest beep
    } else {
      this.currentSet += 1;
      this.phase = "work";
      this.remaining = this.workSeconds;
      beep(660, 200); // rest -> work beep
    }
    this._announcePhase();
  }

  _announcePhase() {
    if (this.callbacks.onPhaseChange) this.callbacks.onPhaseChange(this.phase, this.currentSet, this.remaining);
  }
}
