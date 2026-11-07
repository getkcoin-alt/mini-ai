/* Mini microphone worklet — 20ms mono PCM16 frames. No external SDK.
 * Browser AEC/noise suppression comes from getUserMedia constraints. Server
 * Silero VAD makes speech decisions, not this signal meter.
 */
class MiniCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.phase = 0;
    this.filtered = 0;
    this.frame = new Int16Array(320);
    this.position = 0;
    this.meterFrames = 0;
    this.energy = 0;
    this.active = true;
    this.port.onmessage = (event) => {
      if (event.data?.type === 'stop') this.active = false;
    };
  }
  process(inputs, outputs) {
    // Keep the processor connected to a muted output so browsers keep running.
    const sink = outputs[0]?.[0];
    if (sink) sink.fill(0);
    if (!this.active) return false;
    const mono = inputs[0]?.[0];
    if (!mono || !mono.length) return true;
    const ratio = this.targetRate / sampleRate;
    for (let i = 0; i < mono.length; i++) {
      const value = Number.isFinite(mono[i]) ? mono[i] : 0;
      // A simple anti-alias smoothing step before downsampling. Replace with
      // a bandlimited resampler if measured WER degrades on 48kHz devices.
      this.filtered += Math.min(1, ratio * 1.5) * (value - this.filtered);
      this.energy += value * value;
      this.meterFrames++;
      this.phase += ratio;
      if (this.phase >= 1) {
        this.phase -= 1;
        const clipped = Math.max(-1, Math.min(1, this.filtered));
        this.frame[this.position++] = clipped < 0
          ? Math.round(clipped * 32768) : Math.round(clipped * 32767);
        if (this.position === this.frame.length) {
          const frame = this.frame;
          this.port.postMessage({type: 'pcm', pcm: frame.buffer}, [frame.buffer]);
          this.frame = new Int16Array(320);
          this.position = 0;
        }
      }
      if (this.meterFrames >= sampleRate / 8) {
        this.port.postMessage({type: 'meter', rms: Math.sqrt(this.energy / this.meterFrames)});
        this.meterFrames = 0;
        this.energy = 0;
      }
    }
    return true;
  }
}
registerProcessor('mini-capture', MiniCaptureProcessor);
