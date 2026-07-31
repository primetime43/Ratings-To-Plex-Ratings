import argparse


def main():
    parser = argparse.ArgumentParser(description="Ratings To Plex Ratings")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address for the web GUI (default: 127.0.0.1; remote binds require RTP_ACCESS_TOKEN)",
    )
    parser.add_argument("--port", type=int, default=5000, help="Port for web GUI (default: 5000)")
    args = parser.parse_args()

    from RatingsToPlexRatingsWeb import run_web
    run_web(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
