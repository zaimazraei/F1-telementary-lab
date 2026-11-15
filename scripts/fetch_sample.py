"""Refresh the Bahrain example for every driver without shrinking the archive."""
from fetch_season import main


if __name__ == "__main__":
    raise SystemExit(main(["--event", "Bahrain"]))
