# Table of Contents
- [IMDb Ratings To Plex Ratings](#imdb-ratings-to-plex-ratings)
- [How it works](#how-it-works)
- [Command for creating an exe out of the python file](#command-for-creating-an-exe-out-of-the-python-file)
- [Exporting Your IMDb Ratings](#exporting-your-imdb-ratings)
- [Exporting Your Letterboxd Ratings](#exporting-your-letterboxd-ratings)
- [Requirements](#requirements)

# **IMDb & Letterboxd Ratings To Plex Ratings**

Ratings-To-Plex is a desktop application that allows you to easily sync and transfer your IMDb and Letterboxd ratings to your Plex Media Server. This tool automates the process of updating movie ratings in your Plex libraries, providing a seamless way to ensure that your Plex media collection reflects your ratings from IMDb and Letterboxd.

<details>
  <summary>Click to view screenshots of the program</summary> <br>

v2.1.0 <br>
![image](https://github.com/user-attachments/assets/4299c0f8-d424-4cce-9673-94a5fa85faaa)

v2.0.0 (Uses customtkinter instead of PySimpleGUI UI) <br>
![image](https://github.com/primetime43/Ratings-To-Plex-Ratings/assets/12754111/3ae89679-1e61-4cf1-9b33-1eba558162e4)

v1.2 <br>
![image](https://github.com/primetime43/Ratings-To-Plex-Ratings/assets/12754111/b74b5ecf-84a3-4a7d-96be-3fd8e6ff66b5)

v1.1 <br>
![image](https://github.com/primetime43/Ratings-To-Plex-Ratings/assets/12754111/453b78ab-2b90-4368-a796-feb97d8548be)
</details>

## **How it works**

This application provides a GUI to authenticate with your Plex account, select a server and library, import a CSV file with your IMDb / Letterboxd ratings, and update the ratings in your Plex library. IMDb syncing supports multiple title types (Movies & TV); Letterboxd syncing covers movies.

Here's a brief rundown of the steps:

1. **Log into Plex**: The application uses Plex's OAuth mechanism to authenticate your account. After clicking the "Login to Plex" button, it opens a web browser where you can authorize the app. Once authorized, the app obtains a token to interact with your Plex account.

2. **Select a server**: The application fetches all the servers associated with your Plex account that you own. You can then select the server whose movie ratings you want to update.

3. **Select a library**: Choose the target library (Movies / TV / Mixed). The tool will only update items that exist in that library.

4. **Select a CSV file**: Choose a CSV exported from IMDb (Your Ratings export) or Letterboxd (Data export → ratings.csv). The application parses it and stages rating updates.

5. **Choose media types (IMDb only)**: Toggle which IMDb "Title Type" entries to process: Movie, TV Series, TV Mini Series, TV Movie. (Letterboxd export is movies only.)
6. **Optional – Mark as watched**: If enabled, any item whose rating is set/updated will be marked watched. (Use cautiously—partial watches will become fully watched.)
7. **Optional – Force overwrite ratings**: If enabled, the tool will always reapply the rating even if Plex already shows the same value (bypasses the unchanged skip logic; useful if you cleared a rating in Plex and Plex still returns a stale value through the API).
8. **Click "Update Plex Ratings"**: Starts the background update process. Progress and decisions (updated / skipped / failures) stream into the log panel.

### Rating scale handling

- Plex stores user ratings on a 1–10 scale.
- IMDb ratings are already 1–10, so they are applied directly with no conversion.
- Letterboxd ratings are 0.5–5; the tool multiplies by 2 to map them onto Plex's 1–10 scale (e.g. 4.0 → 8, 3.5 → 7).
- Unchanged ratings are skipped to avoid unnecessary Plex API writes (unless *Force overwrite ratings* is enabled).

### Star ↔ 1–10 Mapping
| Plex UI Stars | Stored Value |
|---------------|--------------|
| 0.5           | 1            |
| 1.0           | 2            |
| 1.5           | 3            |
| 2.0           | 4            |
| 2.5           | 5            |
| 3.0           | 6            |
| 3.5           | 7            |
| 4.0           | 8            |
| 4.5           | 9            |
| 5.0           | 10           |

### Dual-form logging
When a rating is updated the log shows both numeric (1–10) and star forms, e.g.:
`Updated Plex rating for "Inception (2010)" to 8 (4.0★)`

This is informational only; no rounding is applied—IMDb ratings are written exactly as provided; Letterboxd ratings are multiplied by 2.

### Failure & breakdown reporting
At the end of a run a breakdown is logged, for example:
```
Breakdown:
  Skipped unchanged: 42
  Missing IMDb ID: 1
  Invalid rating value: 0
  Not found in Plex: 7
  Type mismatch: 3
  Rate failed errors: 0
  Exported failures: 7
```
If there are unmatched or failed entries a timestamped CSV is written in the working directory:
`Unmatched_imdb_<sourceCSVStem>_YYYYMMDD_HHMMSS.csv`

Each row includes reason details (e.g. Not found, Type mismatch, Invalid rating value, Rate failed).

### Logging & encoding
Two log destinations:
- Rolling main log: `RatingsToPlex.log`
- Per-run log: `RatingsUpdateLog_YYYYMMDD_HHMMSS.log`

Logs are written in UTF-8 so the star symbol (★) is preserved. If the system cannot write a character a sanitized fallback is used so the run continues.

### Performance notes
- IMDb processing uses two strategies: lazy GUID lookup for smaller CSVs (<= 300 rows by default) or a one-time full library scan building a GUID index for larger sets.
- Server & library metadata are prefetched asynchronously after login to reduce perceived latency when selecting servers/libraries.

### Force overwrite vs. unchanged skip
Normally the tool skips writing a rating when the incoming value equals the existing Plex `userRating` (difference < 0.01). Enable *Force overwrite ratings* if:
- You manually cleared a rating in Plex UI but the API still returns the old value.
- You want to ensure a re-write (e.g. to refresh watched-mark side-effects or trigger external agents).

### Safety / best practices
- Always keep a copy of your original CSV exports.
- Test with a small CSV first (filter a few rows) before large batch updates.
- Use *Mark as watched* only if you truly want all updated items marked viewed.

If an error occurs during login or updating, an error line is appended to the run log and shown in the GUI.

---

## **Command for creating an exe out of the python file**
```
pyinstaller --onefile --noconsole RatingsToPlexRatingsGUI.py
```

Tip: Add `--icon <icoPath>` if you have a custom icon.

## **Exporting Your IMDb Ratings:**
1. Go to IMDb and sign into your account.
2. Once you're signed in, click on your username in the top right corner and select "Your Ratings" from the dropdown menu.
3. In the "Your Ratings" page, you will find an "Export" button, usually located on the right side of the page. Click on it.
4. A CSV file will then be downloaded to your device, containing all your IMDb ratings.

## **Exporting Your Letterboxd Ratings:**
1. Go [here to letterboxd](https://letterboxd.com/settings/data/) and export your data.
2. Once exported, use the ratings.csv file in that zip file in the program to update the ratings.

## **Requirements:**
- Python 3.10+
- Packages: `customtkinter`, `plexapi`

Quick install (Windows batch provided):
```
install_requirements.bat
```
or manually:
```
pip install customtkinter plexapi
```

If packaging with PyInstaller ensure the environment where you run `pyinstaller` already has these dependencies installed.

---
### Troubleshooting
**Nothing updates / all say Skipped unchanged**
- Verify the CSV rating values are numeric.
- If you recently cleared ratings in Plex but they still compare equal, enable *Force overwrite ratings* and re-run.

**Many Not found in Plex**
- Ensure you selected the correct library (e.g. TV ratings won’t match in a Movies-only library).
- Confirm IMDb IDs exist in Plex metadata (refresh metadata if recently added).

**Type mismatch entries**
- A CSV title type (e.g. TV Series) didn’t match the Plex item type returned—check that you are targeting the right library.

**Encoding / star character issues**
- Logs are UTF-8; if viewing in a tool that doesn’t support UTF-8 you may see replacement characters.

**PyInstaller exe fails to start**
- Rebuild in a clean virtual environment; ensure `plexapi` imported successfully by running `python -c "import plexapi"` first.

---
Feel free to open issues or submit improvements for new media type handling, additional source platforms, or more granular progress reporting.
