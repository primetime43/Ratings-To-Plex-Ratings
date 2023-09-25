# Table of Contents
- [IMDb Ratings To Plex Ratings](#imdb-ratings-to-plex-ratings)
- [How it works](#how-it-works)
- [Command for creating an exe out of the python file](#command-for-creating-an-exe-out-of-the-python-file)
- [Exporting Your IMDb Ratings](#exporting-your-imdb-ratings)
- [Exporting Your Letterboxd Ratings](#exporting-your-letterboxd-ratings)
- [Requirements](#requirements)

# **IMDb Ratings To Plex Ratings**

This application is designed to help you import your IMDb ratings from an exported CSV file and update your Plex library movie ratings to match the IMDb ratings.

v1.1 <br>
![image](https://github.com/primetime43/Ratings-To-Plex-Ratings/assets/12754111/453b78ab-2b90-4368-a796-feb97d8548be)

v1.2 <br>
![image](https://github.com/primetime43/Ratings-To-Plex-Ratings/assets/12754111/b74b5ecf-84a3-4a7d-96be-3fd8e6ff66b5)

## **How it works**

This script uses a simple GUI to authenticate with your Plex account, select a server, import a CSV file with your IMDb ratings, and update the ratings of your Plex movie library accordingly.

Here's a brief rundown of the steps:

1. **Log into Plex**: The application uses Plex's OAuth mechanism to authenticate your account. After clicking the "Login to Plex" button, it opens a web browser where you can authorize the app. Once authorized, the app obtains a token to interact with your Plex account.

2. **Select a server**: The application fetches all the servers associated with your Plex account that you own. You can then select the server whose movie ratings you want to update.

3. **Select a library**: Select the library to retrieve and update the ratings for this library.

4. **Select a CSV file**: You can choose a CSV file exported from IMDb containing your movie ratings. The application reads the file and prepares to update the ratings on your Plex server.

5. **Update Plex Movie Ratings**: Clicking this button starts the process of updating the movie ratings on the Plex server. The application logs all the operations it performs, which includes connecting to the server, finding the movies, and updating the ratings. 

Please note that the rating scale on Plex is different from IMDb. IMDb uses a scale of 1-10 while Plex uses a scale of 1-5. This script automatically adjusts the ratings from IMDb's scale to Plex's scale.

The application logs all the operations it performs, which includes connecting to the server, finding the movies, and updating the ratings. If an error occurs during the login or updating process, the application will display an error message.

## **Command for creating an exe out of the python file**
```
pyinstaller --onefile --noconsole "Ratings To Plex Ratings.py"
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
- Python 3.10
