import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Ratings To Plex Ratings")
    parser.add_argument("--web", action="store_true", help="Launch web browser GUI instead of desktop GUI")
    parser.add_argument("--port", type=int, default=5000, help="Port for web GUI (default: 5000)")
    args = parser.parse_args()

    if args.web:
        from RatingsToPlexRatingsWeb import run_web
        run_web(port=args.port)
    else:
        from RatingsToPlexRatingsGUI import IMDbRatingsToPlexRatingsApp
        app = IMDbRatingsToPlexRatingsApp()
        app.mainloop()


if __name__ == "__main__":
    main()
