# Table of Contents
- [IMDb Ratings To Plex Ratings](#imdb-ratings-to-plex-ratings)
- [How it works](#how-it-works)
- [Exporting Your IMDb Ratings](#exporting-your-imdb-ratings)
- [Exporting Your Letterboxd Ratings](#exporting-your-letterboxd-ratings)
- [Getting Started](#getting-started)
- [Requirements](#requirements)

# **IMDb & Letterboxd Ratings To Plex Ratings**

Ratings-To-Plex is a web-based tool that allows you to easily sync and transfer your IMDb and Letterboxd ratings to your Plex Media Server. It runs locally in your browser and automates the process of updating movie ratings in your Plex libraries, providing a seamless way to ensure that your Plex media collection reflects your ratings from IMDb and Letterboxd.

v2.3.0<br>
<img width="1909" height="977" alt="image" src="https://github.com/user-attachments/assets/4e18cbf9-02b8-45df-9868-f4697f204910" />
<img width="1904" height="812" alt="image" src="https://github.com/user-attachments/assets/1a6e1637-8ac7-4890-b2eb-cfca3b94b847" />

<details>
  <summary>Click to view screenshots of older versions of the program</summary> <br>

v2.2.0 <br>
![image](https://github.com/user-attachments/assets/baa0ee3f-345b-4c26-bd9b-7c7fb89ded95)

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

The app launches a local web server and opens your browser. From there you can authenticate with Plex, select a server, import a CSV file with your IMDb/Letterboxd ratings, preview what will change, and update the ratings of your Plex movie library accordingly.

Here's a brief rundown of the steps:

1. **Log into Plex**: The application uses Plex's OAuth mechanism to authenticate your account. After clicking the "Login to Plex" button, it opens a web browser where you can authorize the app. Once authorized, the app obtains a token to interact with your Plex account.

2. **Select a server**: The application fetches all the servers associated with your Plex account that you own. You can then select the server whose movie ratings you want to update.

3. **Select a library**: Select the library to retrieve and update the ratings for this library.

4. **Select a CSV file**: Choose a CSV exported from IMDb (Your Ratings export) or Letterboxd (Data export → ratings.csv). The application parses it and stages rating updates.

5. **Choose media types (IMDb only)**: Toggle which IMDb "Title Type" entries to process: Movie, TV Series, TV Mini Series, TV Movie. (Letterboxd export is movies only.)
6. **Preview changes**: Once connected and a CSV is uploaded, the preview panel automatically shows poster art, current vs. new ratings, and match status for every item. Filter by "Will Update", "Unchanged", or "Not on Server" and page through results.
7. **Optional – Mark as watched**: If enabled, any item whose rating is set/updated will be marked watched. (Use cautiously—partial watches will become fully watched.)
8. **Optional – Force overwrite ratings**: If enabled, the tool will always reapply the rating even if Plex already shows the same value (bypasses the unchanged skip logic). The preview updates in real time when this is toggled.
9. **Optional – Search ALL libraries**: When enabled, the tool will search *all* of your owned movie/show libraries (music and photo libraries are excluded) for matches instead of limiting to the single selected library. Use this if you maintain multiple libraries (e.g. "4K Movies" + "HD Movies") and want ratings written wherever the item exists.
10. **Optional – Dry run (preview only)**: If enabled, the tool will NOT write anything to Plex. Instead it will simulate the run and log messages like `"[DRY RUN] Would update ..."` so you can verify counts and a sample before committing. Failure/unmatched CSV export is also skipped in dry-run.
11. **Click "Update Plex Ratings"**: Starts the background (or simulated) update process. Progress streams into the activity log, and when complete, a results dashboard replaces the preview showing exactly what was updated, skipped, or failed.
12. **Optional – Clear All Ratings**: Found in the Danger Zone under Options. Removes all user ratings from the selected library (or all movie/TV libraries). Requires two confirmations before proceeding.

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

### Dual-Form Logging
When a rating is updated the log shows both numeric (1–10) and star forms (e.g. `Updated Plex rating for "Inception (2010)" to 8 (4.0★)`). This is informational only; no rounding is applied—IMDb ratings are written exactly as provided.

The application logs all the operations it performs, which includes connecting to the server, finding the movies, and updating the ratings. If an error occurs during the login or updating process, the application will display an error message.

### Dry Run Mode Details
When the "Dry run" checkbox is selected:
- No ratings are written and nothing is marked watched.
- All other matching / filtering logic still runs so counts are accurate.
- A subset of prospective changes (capped to avoid spamming) is logged with a `[DRY RUN]` prefix.
- Failures/unmatched export CSV is suppressed (so you don’t clutter your folder with test files).
- Final summary line shows `DRY RUN:` instead of `Successfully updated`.

Use a dry run first after large CSV exports or when tuning media type filters to ensure the updates match expectations.

## **Exporting Your IMDb Ratings:**
1. Go to IMDb and sign into your account.
2. Once you're signed in, click on your username in the top right corner and select "Your Ratings" from the dropdown menu.
3. In the "Your Ratings" page, you will find an "Export" button, usually located on the right side of the page. Click on it.
4. A CSV file will then be downloaded to your device, containing all your IMDb ratings.

## **Exporting Your Letterboxd Ratings:**
1. Go [here to letterboxd](https://letterboxd.com/settings/data/) and export your data.
2. Once exported, use the ratings.csv file in that zip file in the program to update the ratings.

## **Getting Started**

1. **Download** the latest release from the [Releases page](https://github.com/primetime43/Ratings-To-Plex-Ratings/releases) and extract the source code zip.
2. **Install Python 3.10+** if you don't already have it.
3. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```
   Or on Windows, double-click `install_requirements.bat`.
4. **Run the app:**
   ```
   python main.py
   ```
   Or double-click `start.bat`. The web UI will open automatically at `http://localhost:5000`.

To use a custom port:
```
python main.py --port 8080
```

## **Requirements:**
- Python 3.10+
- Packages: `plexapi`, `flask`
