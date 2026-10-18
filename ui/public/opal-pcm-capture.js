// Opal microphone capture: forwards mono Float32 frames to the main thread in ~100 ms batches.
class OpalPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.batch = new Float32Array(Math.round(sampleRate / 10))
    this.length = 0
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true
    let offset = 0
    while (offset < channel.length) {
      const count = Math.min(channel.length - offset, this.batch.length - this.length)
      this.batch.set(channel.subarray(offset, offset + count), this.length)
      this.length += count
      offset += count
      if (this.length === this.batch.length) {
        this.port.postMessage(this.batch.slice(0))
        this.length = 0
      }
    }
    return true
  }
}

registerProcessor("opal-pcm-capture", OpalPcmCapture)
