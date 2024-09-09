import csv
import datetime
import logging
import webbrowser
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

# Configure logging
logging.basicConfig(
    filename="RatingsToPlex.log",  # Log file
    level=logging.DEBUG,  # Log level (can change to INFO or ERROR)
    format="%(asctime)s [%(levelname)s] %(message)s",  # Log format
    datefmt="%Y-%m-%d %H:%M:%S"  # Date format
)
logger = logging.getLogger(__name__)

class PlexConnection:
    def __init__(self, account, server, resources):
        self.account = account
        self.server = server
        self.resources = resources
        logger.debug("PlexConnection initialized with account: %s, server: %s", account, server)

    def get_servers(self):
        logger.debug("Fetching servers from Plex account")
        return [resource.name for resource in self.resources]

    def get_libraries(self):
        if self.server:
            logger.debug("Fetching libraries from server: %s", self.server)
            return [section.title for section in self.server.library.sections()]
        logger.warning("Server is not connected. Cannot fetch libraries.")
        return []
    
    def switch_to_server(self, server_name):
        try:
            logger.debug("Switching to server: %s", server_name)
            resource = next((res for res in self.resources if res.name == server_name), None)
            if resource:
                self.server = self.account.resource(resource.name).connect()
                logger.info("Connected to server: %s", server_name)
                return True
        except Exception as e:
            logger.error("Error switching server: %s", e)
        return False

class RatingsToPlexRatingsController:
    def __init__(self, server=None, log_callback=None):
        self.plex_connection = None
        self.log_callback = log_callback
        logger.debug("RatingsToPlexRatingsController initialized")

    def log_message(self, message, log_filename):
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"{timestamp} - {message}\n"
        
        # Log to file for debugging
        logger.info(message)

        # Also log to UI if a callback is provided
        if self.log_callback:
            self.log_callback(full_message)

        # Write to the specified log file
        with open(log_filename, 'a') as log_file:
            log_file.write(full_message)

    def login_and_fetch_servers(self, update_ui_callback):
        logger.info("Initiating Plex login and fetching servers")
        headers = {'X-Plex-Client-Identifier': 'unique_client_identifier'}
        pinlogin = MyPlexPinLogin(headers=headers, oauth=True)
        oauth_url = pinlogin.oauthUrl()
        webbrowser.open(oauth_url)
        pinlogin.run(timeout=120)
        pinlogin.waitForLogin()

        if pinlogin.token:
            logger.info("Plex login successful")
            plex_account = MyPlexAccount(token=pinlogin.token)
            resources = [resource for resource in plex_account.resources() if resource.owned and resource.connections and resource.provides == 'server']
            servers = [resource.name for resource in resources]

            if servers:
                logger.info("Fetched servers: %s", servers)
                self.plex_connection = PlexConnection(plex_account, None, resources)
                update_ui_callback(servers=servers, success=True)
            else:
                logger.warning("No servers found after login")
                update_ui_callback(servers=None, success=False)
        else:
            logger.error("Plex login failed or timed out")
            update_ui_callback(servers=None, success=False)

    def get_servers(self):
        if self.plex_connection:
            return self.plex_connection.get_servers()
        logger.warning("No Plex connection found. Cannot get servers.")
        return []

    def get_libraries(self, server_name):
        if self.plex_connection.switch_to_server(server_name):
            return self.plex_connection.get_libraries()
        else:
            logger.error("Failed to switch to server: %s", server_name)
            return []

    def update_ratings(self, filepath, selected_library, values):
        now = datetime.datetime.now()
        log_filename = f"RatingsUpdateLog_{now.strftime('%Y%m%d_%H%M%S')}.log"
        logger.info("Starting update_ratings with file: %s and library: %s", filepath, selected_library)

        if not self.plex_connection or not self.plex_connection.server:
            logger.error("Not connected to a Plex server")
            self.log_message('Error: Not connected to a Plex server', log_filename)
            return False

        library_section = self.plex_connection.server.library.section(selected_library)
        if not library_section:
            logger.error("Library section %s not found", selected_library)
            self.log_message(f'Error: Library section {selected_library} not found', log_filename)
            return False

        # Process the CSV file and update ratings
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                csv_reader = csv.DictReader(file)

                if values['-IMDB-']:
                    return self.update_ratings_from_imdb(csv_reader, library_section, values, log_filename)
                elif values['-LETTERBOXD-']:
                    return self.update_ratings_from_letterboxd(csv_reader, library_section, values, log_filename)
        except FileNotFoundError:
            logger.error("CSV file not found: %s", filepath)
            self.log_message('Error: File not found', log_filename)
            return False
        except Exception as e:
            logger.error("Error processing CSV: %s", e)
            self.log_message(f'Error processing CSV: {e}', log_filename)
            return False

    def update_ratings_from_imdb(self, csv_reader, library_section, values, log_filename):
        selected_media_types = self._get_selected_media_types(values)
        total_movies = 0
        total_updated_movies = 0

        logger.info("Updating IMDb ratings")
        self.log_message("Updating IMDb ratings", log_filename)  # Log to UI
        guidLookup = {item.guid: item for item in library_section.all()}
        guidLookup.update({guid.id: item for item in library_section.all() for guid in item.guids})

        for movie in csv_reader:
            if movie['Title Type'] not in selected_media_types:
                continue

            imdb_id = movie['Const']
            your_rating = float(movie['Your Rating'])
            plex_rating = your_rating  # Plex uses a 10-point scale internally
            found_movie = guidLookup.get(f'imdb://{imdb_id}')

            if found_movie:
                found_movie.rate(rating=plex_rating)
                message = f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                logger.info(message)
                self.log_message(message, log_filename)  # Send the message to both log file and UI log box
                total_updated_movies += 1
            total_movies += 1

        message = f"Successfully updated {total_updated_movies} out of {total_movies} movies"
        logger.info(message)
        self.log_message(message, log_filename)  # Log success message to UI
        return True

    def update_ratings_from_letterboxd(self, csv_reader, library_section, values, log_filename):
        total_movies = 0
        total_updated_movies = 0

        logger.info("Updating Letterboxd ratings")
        library_movies = {(item.title, str(item.year)): item for item in library_section.all()}

        for movie in csv_reader:
            try:
                name = movie.get('Name', '').strip()
                year = movie.get('Year', '').strip()
                rating_str = movie.get('Rating', '').strip()

                if not name or not year or not rating_str:
                    continue

                your_rating = float(rating_str) * 2  # Convert Letterboxd ratings to 10-point scale
                plex_rating = your_rating

                search_key = (name, year)
                found_movie = library_movies.get(search_key)

                if found_movie:
                    found_movie.rate(rating=plex_rating)
                    message = f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                    logger.info(message)
                    self.log_message(message, log_filename)  # Log both to file and UI
                    total_updated_movies += 1
            except Exception as e:
                logger.error('Error processing "%s (%s)": %s. Skipping.', name, year, e)
            total_movies += 1

        message = f"Successfully updated {total_updated_movies} out of {total_movies} movies"
        logger.info(message)
        self.log_message(message, log_filename)  # Log success message to UI
        return True

    def _get_selected_media_types(self, values):
        selected_media_types = []
        
        # Add media types based on selected checkboxes
        if values['-MOVIE-']:
            selected_media_types.append('Movie')
        if values['-TVSERIES-']:
            selected_media_types.append('TV Series')
        if values['-TVMINISERIES-']:
            selected_media_types.append('TV Mini Series')
        if values['-TVMOVIE-']:
            selected_media_types.append('TV Movie')
        if values.get('-SHORT-', False):
            selected_media_types.append('Short')
        if values.get('-TVEPISODE-', False):
            selected_media_types.append('TV Episode')
        
        logger.debug("Selected media types: %s", selected_media_types)
        return selected_media_types
