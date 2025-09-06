
# Storing API Keys

Certain plugins, like the AI Image plugin, require API credentials to function. These credentials must be stored in a .env file located at the root of the project. Once you have your API token, follow these steps:

1. SSH into your Raspberry Pi and navigate to the InkyPi directory:
    ```bash
    cd InkyPi
    ```
2. Create or edit the .env file using your preferred text editor (e.g., vi, nano):
    ```bash
    vi .env
    ```
3. Add your API keys following format, with one line per key:
    ```
    PLUGIN_KEY=your-key
    ```
4. Save the file and exit the editor

## Manage API Keys from the Web UI

You can now manage your API keys directly from the InkyPi web UI:

- Open the Settings page and click "Manage API Keys".
- The page shows whether each key is configured. Values are masked (only last 4 characters shown).
- Enter a new value to create or update a key. Use the Delete button to remove a key.
- Keys are written to the `.env` file on the device and loaded at runtime. They are never stored in `device.json` or other configs.

Notes:
- In development, `.env` is expected at the project root (repo root).
- In production (installed via `install/install.sh`), `.env` is located at `/usr/local/inkypi/.env` and is created with `0600` permissions. The systemd service also references this file via `EnvironmentFile`.
- `.env` is git-ignored to prevent accidental commits.

## Open AI Key

Required for the AI Image and AI Text Plugins

- Login or create an account on the [Open AI developer platform](https://platform.openai.com/docs/overview)
- Crate a secret key from the API Keys tab in the Settings page
    - It is recommended to set up Auto recharge (found in the "Billing" tab)
    - Optionally set a Budge Limit in the Limits tab
- Store your key in the .env file with the key OPEN_AI_SECRET
    ```
    OPEN_AI_SECRET=your-key
    ```

## Open Weather Map Key

Required for the Weather Plugin

- Login or create an account on [OpenWeatherMap](https://home.openweathermap.org/users/sign_in)
    - Verify your email after signing up
- The weather plugin uses the [One Call API 3.0](https://openweathermap.org/price) which requires a subscription but is free for up to 1,000 requests per day.
    - Subscribe at [One Call API 3.0 Subscription](https://home.openweathermap.org/subscriptions/billing_info/onecall_30/base?key=base&service=onecall_30)
    - Follow the instructions to complete the subscription.
    - Navigate to [Your Subscriptions](https://home.openweathermap.org/subscriptions) and set "Calls per day (no more than)" to 1,000 to avoid exceeding the free limit
- Store your api key in the .env file with the key OPEN_WEATHER_MAP_SECRET
    ```
    OPEN_WEATHER_MAP_SECRET=your-key
    ```

## NASA Astronomy Picture Of the Day key

Required for the APOD Plugin

- Request an API key on [NASA APIs](https://api.nasa.gov/)
   - Fill your First name, Last name, and e-mail address
- The APOD plugin uses the [NASA APIs](https://api.nasa.gov/)
   - Free for up to 1,000 requests per hour
- Store your api key in the .env file with the key NASA_SECRET
    ```
    NASA_SECRET=your-key
    ```

## Unsplash

Required for the Unsplash Plugin
 
- Register an account from https://unsplash.com/developers 
- Go to https://unsplash.com/oauth/applications 
- Create an app and open it
- Your KEY is listed as `Access Key`
- Save your access key in `/.env` file as `UNSPLASH_ACCESS_KEY=`