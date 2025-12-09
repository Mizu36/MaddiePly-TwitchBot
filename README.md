# MaddiePly Twitch Bot

A full-featured, GUI-driven Twitch automation suite that blends live chat moderation, voiced responses, OBS scene control, Discord announcements, and channel-point mini workflows into a single desktop app. The project couples a Tkinter control panel with a TwitchIO bot, SQLite-backed settings, voice synthesis (ElevenLabs/Azure), and first-party integrations such as Discord and Google Sheets.

## Feature Highlights
- **GUI Control Center** – Manage settings, prompts, commands, scheduled messages, hotkeys, and testing payloads through a Tkinter application with inline validation and tooltips.
- **Voice & Audio Pipeline** – Stream-ready spoken replies powered by ElevenLabs (primary) with Azure Cognitive Services as an automatic backup; includes audio-device routing, warmups, and waveform-driven OBS avatar animation.
- **Chat Automation** – Respond to chat in real time, trigger AI-crafted replies, fire off voiced sound FX, and keep bespoke event queues running via the `EventManager` and `MessageScheduler`.
- **OBS Orchestration** – Display memes/GIFs, animate on-screen assistants, and manage transforms through the bundled OBS WebSocket client.
- **Custom Channel Rewards** – Build multi-step redemption flows (chat replies, AI prompts, memes, sounds, timeouts, waits, etc.) with the Redemption Builder UI; toggle entries on/off or randomize sequences with a click.
- **Testing Harness** – Simulate Twitch EventSub payloads (chat, follows, raids, hype trains, shared chat, etc.) directly from the GUI to verify behavior without waiting for live traffic.
- **Discord & Shared Chat Hooks** – Optional Discord bot thread for announcements plus shared-chat enablement that respects database toggles.
- **Quotes via Google Sheets** – Optional Google Sheets integration for storing and retrieving on-stream quotes using a service account.
- **Hotkeys Everywhere** – Global hotkey listener lets you trigger actions while streaming; GUI exposes capture dialogs with automatic conflict handling.
- **Self-Healing Media** – Automated ffmpeg provisioning (via `local-ffmpeg`) plus background cleanup of generated memes, screenshots, and voice files keeps disk usage low.

## Quick Start
1. **Clone & Open:** Pull this repository and open it in VS Code (or your editor of choice).
2. **Run the launcher:** During development run `python launcher.py`. For stream/production machines, build the bundled executable via `pyinstaller --noconfirm --clean maddieply.spec` (details below) and launch `dist/MaddiePly/MaddiePly.exe`. The launcher will:
   - Ensure `media/`, `data/`, and `ffmpeg_bin/` exist next to the executable.
   - Scaffold `.env` from a template when it is missing.
   - Validate required secrets and prompt for broadcaster/bot usernames so it can fetch `BOT_ID`/`OWNER_ID` automatically.
   - Hand control over to the Tkinter GUI once validation succeeds.
3. **Fill in `.env`:** Enter all required API keys (see sections below). Rerun the launcher or packaged executable until the validation step passes.
4. **Use the GUI:** Configure prompts, commands, hotkeys, and run built-in test events before going live.

## Building the Executable (PyInstaller)
1. Install PyInstaller into your development environment if you have not already: `pip install pyinstaller`.
2. From the project root, run `pyinstaller --noconfirm --clean maddieply.spec`.
3. The build drops a self-contained folder at `dist/MaddiePly/` with `MaddiePly.exe` as the launcher. Keep `media/`, `data/`, and `ffmpeg_bin/` with the executable; the spec already copies your checked-in assets.
4. Place your `.env` and (optionally) `credentials.json` beside the executable before first launch. If `.env` is missing, the launcher writes a template and exits so you can populate it.
5. Re-run the build command whenever you change Python dependencies or add new media assets that must ship with the bot.

## Required Accounts & Secrets
All secrets live in the repo-level `.env`. Each key maps one-to-one with the instructions below.

### 1. Twitch Developer Application
1. Sign in at [dev.twitch.tv](https://dev.twitch.tv) and open **Your Console → Register Your Application**.
2. Choose a memorable name (users will see it during authorization).
3. Add both redirect URLs:
   - `http://localhost:4343/oauth`
   - `http://localhost:4343/oauth/callback`
4. Category: **Chat Bot**. Client Type: **Confidential**.
5. Note the generated **Client ID** and click **New Secret** for the **Client Secret**.
6. Update `.env`:
   ```
   TWITCH_CLIENT_ID=your_client_id
   TWITCH_APP_SECRET=your_client_secret
   ```

### 2. Bot & Broadcaster IDs
- When `.env` lacks `BOT_ID` or `OWNER_ID`, the launcher (`python launcher.py` or the packaged `MaddiePly.exe`) prompts for the bot and broadcaster usernames, calls the Twitch API, and writes the numeric IDs automatically.
- To refresh the IDs later, clear those fields in `.env` and rerun the launcher so it can fetch them again.
- Use separate Twitch accounts for bot and broadcaster to ensure moderator/editor scopes work correctly.

### 3. ElevenLabs (Required)
1. Create an account at [elevenlabs.io](https://elevenlabs.io).
2. In the left sidebar, expand **Developers → API Keys** and create a new unrestricted key.
3. Copy the key into `.env`:
   ```
   ELEVENLABS_API_KEY=your_elevenlabs_key
   ```

### 4. OpenAI (Required)
1. Visit [platform.openai.com](https://platform.openai.com) and sign in (ChatGPT accounts work).
2. Create a project, then from the dashboard choose **API Keys → Create new secret key**.
3. Attach the key to your project, copy it once (OpenAI will not show it again), and fund the project with at least **$5** so requests are enabled.
4. Update `.env`:
   ```
   OPENAI_API_KEY=your_openai_key
   ```

### 5. Azure Speech (Required)
1. Sign in at [portal.azure.com](https://portal.azure.com).
2. Create a **Speech Services** resource (Subscribe → Speech → Create). Use the **F0** plan so usage stays in the free tier.
3. Choose a region (lowercase, single word) and note it for `AZURE_TTS_REGION`.
4. Once deployment finishes, open the resource and copy **Key 1** for `AZURE_TTS_KEY`. Occasionally the key appears a few hours later—check back if blank.
5. `.env` entries:
   ```
   AZURE_TTS_KEY=your_azure_speech_key
   AZURE_TTS_REGION=yourregion
   ```

### 6. Discord Bot Token (Optional)
If you want Discord announcements, create a Discord bot, copy its token, and set `DISCORD_TOKEN=`. Leaving it blank keeps Discord features disabled.

### 7. Google Sheets Credentials (Optional)
1. In [Google Cloud Console](https://console.cloud.google.com/welcome/new), create a project.
2. Enable **Google Drive API** and **Google Sheets API**.
3. Create a **Service Account**, then generate a JSON key (download it and place `credentials.json` in the project root).
4. Share your Quotes spreadsheet with the service account email so it can read/write.
5. Inside the GUI, paste the Sheet ID into the `Google Sheets Quotes Sheet ID` field (the Sheet ID is the long string in the sheet URL between `/d/` and `/edit`).

## OAuth Authorization Flow
The bot needs user tokens for both the bot account and the broadcaster account.
1. Launch the app via `python launcher.py` or by running the packaged `MaddiePly.exe`. The Tkinter GUI spins up the FastAPI OAuth server on `http://localhost:4343`.
2. While logged in as the **bot account**, hit Twitch’s authorize endpoint (replace `YOUR_CLIENT_ID` with the value from `.env`):

   ```
   https://id.twitch.tv/oauth2/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=http%3A%2F%2Flocalhost%3A4343%2Foauth&scope=user:read:chat%20user:write:chat%20user:bot%20user:manage:whispers%20moderator:manage:banned_users%20moderator:read:followers%20moderator:read:suspicious_users%20moderator:manage:shield_mode%20moderator:manage:shoutouts%20moderator:manage:automod%20moderator:manage:chat_settings%20bits:read%20channel:read:hype_train&force_verify=true
   ```
   Twitch redirects back to `http://localhost:4343/oauth?code=...`; the GUI watches that FastAPI server and stores the token pair automatically.
3. Log out, switch to the **broadcaster account**, and authorize using the production client ID again:
   ```
   https://id.twitch.tv/oauth2/authorize?response_type=code&client_id=YOUR_CLIENT_ID&redirect_uri=http%3A%2F%2Flocalhost%3A4343%2Foauth&scope=channel:read:subscriptions%20channel:manage:redemptions%20channel:read:charity%20channel:read:goals%20channel:manage:polls%20channel:manage:predictions%20channel:bot%20channel:edit:commercial%20channel:read:ads%20bits:read%20channel:read:hype_train&force_verify=true
   ```
4. Restart the bot to pick up both token entries. Ensure the bot account has the **Editor** role on the channel so ad/commercial scopes function.

## Running the Bot Day-to-Day
1. Double-click `MaddiePly.exe` (from `dist/MaddiePly/`) or run `python launcher.py` while developing. A console window remains open so you can see validation messages, Twitch ID prompts, and tracebacks if anything fails before the GUI starts.
2. Configure settings, prompts, redemptions, and scheduled messages inside the GUI tabs.
3. Use the **Testing** tab to simulate Twitch events before going live.
4. Keep the GUI open during your stream—background managers (Twitch bot, Discord thread, OBS sync, timers) remain active as long as the GUI is running.
5. Exit via the window close button to shut down the SQLite pool, bot, and background services cleanly.

## Troubleshooting Tips
- **Missing Secrets:** The launcher halts with a descriptive message when `.env` values are blank. Fill them and rerun.
- **ffmpeg Popups:** Dependencies bundle ffmpeg automatically; no manual PATH edits are required.
- **BOT_ID/OWNER_ID still blank:** Delete their values from `.env`, rerun the start script, and re-enter the Twitch usernames when prompted.
- **Azure Key Delay:** If Azure shows no keys yet, wait a few hours—Microsoft sometimes provisions the Speech resource asynchronously.
- **Google Sheets Disabled:** When credentials are missing/invalid, related toggles are greyed out with tooltips explaining why.

If you run into issues or have feature ideas, open an issue.
