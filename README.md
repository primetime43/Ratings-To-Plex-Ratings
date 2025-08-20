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

This script uses a simple GUI to authenticate with your Plex account, select a server, import a CSV file with your IMDb/Letterboxd ratings, and update the ratings of your Plex movie library accordingly.

Here's a brief rundown of the steps:

1. **Log into Plex**: The application uses Plex's OAuth mechanism to authenticate your account. After clicking the "Login to Plex" button, it opens a web browser where you can authorize the app. Once authorized, the app obtains a token to interact with your Plex account.

2. **Select a server**: The application fetches all the servers associated with your Plex account that you own. You can then select the server whose movie ratings you want to update.

3. **Select a library**: Select the library to retrieve and update the ratings for this library.

4. **Select a CSV file**: Choose a CSV exported from IMDb (Your Ratings export) or Letterboxd (Data export → ratings.csv). The application parses it and stages rating updates.

5. **Choose media types (IMDb only)**: Toggle which IMDb "Title Type" entries to process: Movie, TV Series, TV Mini Series, TV Movie. (Letterboxd export is movies only.)
6. **Optional – Mark as watched**: If enabled, any item whose rating is set/updated will be marked watched. (Use cautiously—partial watches will become fully watched.)
7. **Optional – Force overwrite ratings**: If enabled, the tool will always reapply the rating even if Plex already shows the same value (bypasses the unchanged skip logic; useful if you cleared a rating in Plex and Plex still returns a stale value through the API).
8. **Optional – Update items outside selected library**: When enabled, the tool will search *all* of your owned movie/show libraries for matches instead of limiting to the single selected library. Use this if you maintain multiple libraries (e.g. "4K Movies" + "HD Movies") and want ratings written wherever the item exists. (The dropdown library is still required for UI flow, but matching spans every movie/show library.)
9. **Optional – Dry run (preview only)**: If enabled, the tool will NOT write anything to Plex. Instead it will simulate the run and log messages like `"[DRY RUN] Would update ..."` so you can verify counts and a sample before committing. Failure/unmatched CSV export is also skipped in dry-run.
10. **Click "Update Plex Ratings"**: Starts the background (or simulated) update process. Progress and decisions (updated / skipped / failures) stream into the log panel.

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

## **Command for creating an exe out of the python file**
```
pyinstaller --onefile --noconsole RatingsToPlexRatingsGUI.py
```

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
