"""
Interactive Voice Conversation with Gemini Live (Direct AI Studio connection).
Listens from microphone and plays back audio responses using sounddevice and google-genai.
"""
import asyncio
import os
import queue
import sys
import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types

# Audio configuration (Gemini Live outputs 24kHz PCM audio)
SAMPLE_RATE = 24000
CHANNELS = 1

async def voice_chat():
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set.")
        print("Please set it with: $env:GEMINI_API_KEY='your_api_key'")
        return

    client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.8-live")
    
    print(f"Connecting to Google AI Studio Live ({model})...")
    print("Press Ctrl+C to exit.")

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part(
                text=(
                    "You are Opal, a tiny, friendly AI mascot sidekick integrated into Amber. "
                    "You talk through chat context and user queries in detail using voice. "
                    "Be concise, conversational, and helpful across multiple turns."
                )
            )]
        )
    )

    audio_queue = queue.Queue()
    audio_buffer = bytearray()

    def playback_callback(outdata, frames, time, status):
        nonlocal audio_buffer
        bytes_needed = frames * CHANNELS * 2  # 2 bytes per int16 sample
        
        while len(audio_buffer) < bytes_needed:
            try:
                chunk = audio_queue.get_nowait()
                audio_buffer.extend(chunk)
            except queue.Empty:
                break
                
        if len(audio_buffer) >= bytes_needed:
            data = audio_buffer[:bytes_needed]
            del audio_buffer[:bytes_needed]
            outdata[:] = np.frombuffer(data, dtype=np.int16).reshape(-1, CHANNELS)
        else:
            data = audio_buffer
            audio_buffer.clear()
            if len(data) > 0:
                arr = np.frombuffer(data, dtype=np.int16)
                outdata[:len(arr)] = arr.reshape(-1, CHANNELS)
                outdata[len(arr):] = 0
            else:
                outdata[:] = 0

    # Start audio output stream
    stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16', callback=playback_callback)
    
    with stream:
        try:
            async with client.aio.live.connect(model=model, config=config) as session:
                print("\nConnected! Start speaking/typing to Opal (Gemini Live)...")

                async def receive_loop():
                    while True:
                        try:
                            async for response in session.receive():
                                server_content = response.server_content
                                if server_content:
                                    model_turn = server_content.model_turn
                                    if model_turn:
                                        for part in model_turn.parts:
                                            if part.text:
                                                print(f"Opal: {part.text}")
                                            if part.inline_data:
                                                # Audio data from model
                                                audio_bytes = part.inline_data.data
                                                if audio_bytes:
                                                    audio_queue.put(audio_bytes)
                                    if server_content.turn_complete:
                                        print("[Turn complete]")
                        except Exception as e:
                            # If connection drops or stream resets, brief pause before retrying
                            await asyncio.sleep(0.1)

                async def input_loop():
                    loop = asyncio.get_running_loop()
                    while True:
                        text_input = await loop.run_in_executor(None, input, "You: ")
                        if text_input.strip():
                            await session.send_client_content(
                                turns=types.Content(
                                    role="user",
                                    parts=[types.Part(text=text_input)]
                                ),
                                turn_complete=True
                            )

                await asyncio.gather(receive_loop(), input_loop())

        except Exception as e:
            print(f"\nLive session error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(voice_chat())
    except KeyboardInterrupt:
        print("\nExited voice chat.")
