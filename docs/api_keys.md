# Storing API Keys

Some plugins need a key from an outside service before they can render.

| Key name | Plugins | Get one from |
|---|---|---|
| `OPEN_AI_SECRET` | AI Image, AI Text (OpenAI models) | [OpenAI](#openai-key) |
| `GOOGLE_AI_SECRET` | AI Image, AI Text (Google models) | [Google AI](#google-ai-key) |
| `OPEN_WEATHER_MAP_SECRET` | Weather | [OpenWeatherMap](#openweathermap-key) |
| `NASA_SECRET` | NASA Astronomy Picture of the Day | [NASA](#nasa-astronomy-picture-of-the-day-key) |
| `UNSPLASH_ACCESS_KEY` | Unsplash | [Unsplash](#unsplash-key) |
| `GITHUB_SECRET` | GitHub | [GitHub](#github-key) |
| `IMMICH_KEY` | Image Album (Immich) | [Immich](#immich-key) |

## Add, change or remove a key

Use the web UI:

1. Open InkyPi in a browser and choose **API Keys** in the sidebar. A plugin
   that needs a key also has a **Manage keys** button on its page.
2. To add a key, choose **Add API Key**, enter the key name from the table
   (for example `NASA_SECRET`) and paste the value.
3. To replace a key, for example after rotating it, type the new value into
   its row. A row left blank keeps its current value.
4. To remove a key, choose **×** on its row.
5. Save.

Plugins read their key on every refresh, so a change applies from the
plugin's next refresh. If a plugin still uses the old key, restart the
service with `sudo systemctl restart inkypi`.

### Editing the file directly

The keys are stored in `/usr/local/inkypi/.env`, one `KEY=value` per line:

```
NASA_SECRET=your-key
```

This is **not** the `.env` in your clone of the repository. The service reads
`$PROJECT_DIR/.env`, and the launcher sets `PROJECT_DIR=/usr/local/inkypi`.
The file is readable only by its owner (mode `0600`), so edit it with sudo
over SSH:

```bash
sudo nano /usr/local/inkypi/.env
```

`.env` holds API keys only. The app reads each key from it when a plugin
needs one and never loads the file into its environment, so other settings
in it (`INKYPI_*`, `HTTPS_PROXY`, `OPENAI_BASE_URL`) have no effect. Put
`INKYPI_*` settings in a systemd drop-in instead
(`sudo systemctl edit inkypi`, then `Environment=NAME=value` under
`[Service]`).

**Backups.** Settings → Backup can include your API keys, but only when a PIN
is set (see [auth.md](auth.md)). Without a PIN every page is open to anything
on your network, so a backup with keys in it would be too.

## OpenAI Key

Used by the AI Image and AI Text plugins with OpenAI models.

- Log in to or create an account on the [OpenAI developer platform](https://platform.openai.com/docs/overview).
- Create a secret key from the **API Keys** tab of the Settings page.
    - Consider turning on auto recharge (in the **Billing** tab).
    - Optionally set a budget limit in the **Limits** tab.
- Save it as `OPEN_AI_SECRET`.

## Google AI Key

Used by the AI Image and AI Text plugins with Google models.

- Create a key in [Google AI Studio](https://aistudio.google.com/apikey).
- Save it as `GOOGLE_AI_SECRET`.

## OpenWeatherMap Key

Used by the Weather plugin.

- Log in to or create an account on [OpenWeatherMap](https://home.openweathermap.org/users/sign_in).
    - Verify your email after signing up.
- The plugin uses the [One Call API 3.0](https://openweathermap.org/price), which needs a subscription but is free for up to 1,000 requests a day.
    - Subscribe at [One Call API 3.0 Subscription](https://home.openweathermap.org/subscriptions/billing_info/onecall_30/base?key=base&service=onecall_30) and follow the instructions.
    - In [Your Subscriptions](https://home.openweathermap.org/subscriptions), set "Calls per day (no more than)" to 1,000 so you can't exceed the free limit.
- Save it as `OPEN_WEATHER_MAP_SECRET`.

## NASA Astronomy Picture of the Day Key

Used by the NASA Astronomy Picture of the Day plugin.

- Request a key on [NASA APIs](https://api.nasa.gov/) with your first name, last name and email address.
    - It's free for up to 1,000 requests an hour.
- Save it as `NASA_SECRET`.

## Unsplash Key

Used by the Unsplash plugin.

- Register at <https://unsplash.com/developers>.
- Go to <https://unsplash.com/oauth/applications>, create an app and open it.
- Your key is listed as **Access Key**.
- Save it as `UNSPLASH_ACCESS_KEY`.

## GitHub Key

Used by the GitHub plugin.

- In your [GitHub settings](https://github.com/settings/profile), go to **Developer settings** and create a personal access token (classic).
- Give it the `read:user` scope and generate it.
- Save it as `GITHUB_SECRET`.

## Immich Key

Used by the Image Album plugin with the Immich provider.

- Log in to your Immich instance (for example <https://my.immich.app/>).
- Under **Account Settings > API Keys**, create a key with the `asset.read`, `asset.download` and `album.read` permissions.
- Save it as `IMMICH_KEY`.
