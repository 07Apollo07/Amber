# Google AI Studio Direct Live Connection Tests

This folder contains test scripts for connecting directly to Google AI Studio using the `google-genai` SDK and Gemini Live (`gemini-3.8-flash-live`).

## Running Tests

1. Set your Google AI Studio API key:
   ```powershell
   $env:GEMINI_API_KEY="your-api-key-here"
   ```

2. Run the live connection test:
   ```powershell
   .\api\.venv\Scripts\python.exe api\test\test_aistudio_live.py
   ```

3. Run the interactive voice chat test (with sounddevice audio playback):
   ```powershell
   .\api\.venv\Scripts\python.exe api\test\test_aistudio_voice.py
   ```
