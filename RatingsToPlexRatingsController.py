import csv
import datetime
import logging
import threading
import time
import webbrowser
from typing import Callable, List, Optional
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

# Configure logging
logging.basicConfig(
    filename="RatingsToPlex.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class PlexConnection:
    """Wraps a Plex account/resources with lightweight caching for faster UI interactions."""

    def __init__(self, account, server, resources):
        self.account = account
        self.server = server
        self.resources = resources
        self._server_cache = {}  # server_name -> connected PlexServer
        self._libraries_cache = {}  # server_name -> list[str]
        self._lock = threading.Lock()
        logger.debug("PlexConnection initialized with account: %s, server: %s", account, server)

    def get_servers(self) -> List[str]:
        return [resource.name for resource in self.resources]

    def switch_to_server(self, server_name: str) -> bool:
        # Reuse cached connection if available
        with self._lock:
            if server_name in self._server_cache:
                self.server = self._server_cache[server_name]
                logger.debug("Using cached server connection for: %s", server_name)
                return True
        try:
            resource = next((res for res in self.resources if res.name == server_name), None)
            if resource:
                connected = self.account.resource(resource.name).connect(timeout=8)  # type: ignore[arg-type]
                with self._lock:
                    self._server_cache[server_name] = connected
                self.server = connected
                logger.info("Connected to server: %s", server_name)
                return True
        except Exception as e:
            logger.error("Error switching server: %s", e)
        return False

    def get_libraries(self) -> List[str]:
        if not self.server:
            logger.warning("Server is not connected. Cannot fetch libraries.")
            return []
        server_name = getattr(self.server, 'friendlyName', None) or getattr(self.server, 'name', None)
        if server_name and server_name in self._libraries_cache:
            logger.debug("Libraries cache hit for server: %s", server_name)
            return self._libraries_cache[server_name]
        try:
            libs = [section.title for section in self.server.library.sections()]
            if server_name:
                self._libraries_cache[server_name] = libs
            logger.debug("Fetched %d libraries for server %s", len(libs), server_name)
            return libs
        except Exception as e:
            logger.error("Failed to fetch libraries from server: %s", e)
            return []

    def prefetch_all_libraries_async(self, log_fn: Optional[Callable[[str], None]] = None):
        """Background warm-up of server connections and library lists for all servers."""

        def _worker():
            for res in self.resources:
                name = res.name
                if name in self._libraries_cache:
                    continue
                try:
                    start = time.perf_counter()
                    if name not in self._server_cache:
                        connected = self.account.resource(res.name).connect(timeout=8)  # type: ignore[arg-type]
                        with self._lock:
                            self._server_cache[name] = connected
                    server_obj = self._server_cache[name]
                    libs = [s.title for s in server_obj.library.sections()]
                    self._libraries_cache[name] = libs
                    duration = time.perf_counter() - start
                    if log_fn:
                        log_fn(f"Prefetched libraries for '{name}' ({len(libs)} libraries) in {duration:.2f}s")
                except Exception as e:  # pragma: no cover (best-effort prefetch)
                    if log_fn:
                        log_fn(f"Prefetch failed for '{name}': {e}")
        threading.Thread(target=_worker, daemon=True).start()


class RatingsToPlexRatingsController:
    def __init__(self, server=None, log_callback=None):
        self.plex_connection = None
        self.log_callback = log_callback
        logger.debug("RatingsToPlexRatingsController initialized")

    def log_message(self, message, log_filename):
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"{timestamp} - {message}\n"
        logger.info(message)
        if self.log_callback:
            self.log_callback(full_message)
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
            resources = [r for r in plex_account.resources() if r.owned and r.connections and r.provides == 'server']
            servers = [r.name for r in resources]
            if servers:
                logger.info("Fetched servers: %s", servers)
                self.plex_connection = PlexConnection(plex_account, None, resources)
                # No persistent seeding; rely on live prefetch
                self.plex_connection.prefetch_all_libraries_async(log_fn=lambda m: logger.debug(m))
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
        logger.error("Failed to switch to server: %s", server_name)
        return []

    def get_libraries_async(self, server_name: str, callback: Callable[[List[str]], None]):
        def _worker():
            libs = self.get_libraries(server_name)
            try:
                callback(libs)
            except Exception as e:  # pragma: no cover
                logger.error("Library callback error: %s", e)
        threading.Thread(target=_worker, daemon=True).start()

    # Persistent cache methods removed

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
        self.log_message("Updating IMDb ratings", log_filename)
        all_items = library_section.all()
        guidLookup = {item.guid: item for item in all_items if getattr(item, 'guid', None)}
        for item in all_items:
            for guid in getattr(item, 'guids', []) or []:
                guidLookup[guid.id] = item

        def imdb_type_to_plex_types(imdb_type):
            mapping = {
                'Movie': {'movie'},
                'TV Movie': {'movie'},
                'Short': {'movie'},
                'TV Series': {'show'},
                'TV Mini Series': {'show'},
                'TV Episode': {'episode'},
            }
            return mapping.get(imdb_type, set())

        for movie in csv_reader:
            if movie['Title Type'] not in selected_media_types:
                continue
            imdb_id = movie.get('Const')
            if not imdb_id:
                continue
            try:
                your_rating = float(movie.get('Your Rating', '').strip())
            except ValueError:
                continue
            plex_rating = your_rating
            found_movie = guidLookup.get(f'imdb://{imdb_id}')
            if found_movie:
                expected_types = imdb_type_to_plex_types(movie['Title Type'])
                item_type = getattr(found_movie, 'type', None)
                if expected_types and item_type not in expected_types:
                    skip_msg = (f'Skipped "{found_movie.title} ({getattr(found_movie, "year", "?")})" - '
                                f'type mismatch (CSV: {movie["Title Type"]}, Plex: {item_type})')
                    logger.debug(skip_msg)
                    self.log_message(skip_msg, log_filename)
                else:
                    found_movie.rate(rating=plex_rating)
                    message = f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                    logger.info(message)
                    self.log_message(message, log_filename)
                    if values.get("-WATCHED-", False):
                        try:
                            found_movie.markWatched()
                            watched_msg = f'Marked "{found_movie.title} ({found_movie.year})" as watched'
                            logger.info(watched_msg)
                            self.log_message(watched_msg, log_filename)
                        except Exception as e:
                            error_msg = f"Error marking as watched for {found_movie.title}: {e}"
                            logger.error(error_msg)
                            self.log_message(error_msg, log_filename)
                    total_updated_movies += 1
            total_movies += 1
        message = f"Successfully updated {total_updated_movies} out of {total_movies}"
        logger.info(message)
        self.log_message(message, log_filename)
        return True

    def update_ratings_from_letterboxd(self, csv_reader, library_section, values, log_filename):
        total_movies = 0
        total_updated_movies = 0
        logger.info("Updating Letterboxd ratings")
        library_movies = {}
        for item in library_section.all():
            if getattr(item, 'type', None) != 'movie':
                continue
            key = (item.title.lower().strip(), str(item.year))
            library_movies.setdefault(key, item)
        for movie in csv_reader:
            try:
                name = movie.get('Name', '').strip()
                year = movie.get('Year', '').strip()
                rating_str = movie.get('Rating', '').strip()
                if not name or not year or not rating_str:
                    continue
                your_rating = float(rating_str) * 2
                plex_rating = your_rating
                search_key = (name.lower(), year)
                found_movie = library_movies.get(search_key)
                if found_movie:
                    found_movie.rate(rating=plex_rating)
                    message = f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                    logger.info(message)
                    self.log_message(message, log_filename)
                    if values.get("-WATCHED-", False):
                        try:
                            found_movie.markWatched()
                            watched_msg = f'Marked "{found_movie.title} ({found_movie.year})" as watched'
                            logger.info(watched_msg)
                            self.log_message(watched_msg, log_filename)
                        except Exception as e:
                            error_msg = f"Error marking as watched for {found_movie.title}: {e}"
                            logger.error(error_msg)
                            self.log_message(error_msg, log_filename)
                    total_updated_movies += 1
            except Exception as e:
                logger.error('Error processing "%s (%s)": %s. Skipping.', name, year, e)
            total_movies += 1
        message = f"Successfully updated {total_updated_movies} out of {total_movies}"
        logger.info(message)
        self.log_message(message, log_filename)
        return True

    def _get_selected_media_types(self, values):
        selected_media_types = []
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

