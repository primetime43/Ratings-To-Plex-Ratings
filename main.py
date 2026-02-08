import argparse


def main():
    parser = argparse.ArgumentParser(description="Ratings To Plex Ratings")
    parser.add_argument("--port", type=int, default=5000, help="Port for web GUI (default: 5000)")
    args = parser.parse_args()

    from RatingsToPlexRatingsWeb import run_web
    run_web(port=args.port)


if __name__ == "__main__":
    main()
