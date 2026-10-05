"""
Seed script — imports Pedro's PS3 game collection.

Run from the game-vault root:
    source venv/bin/activate
    python -m scripts.seed_data

Requires DATABASE_URL in config/.env
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv("config/.env")

from src.api.db import get_conn

PSN_USERNAME = "TrophyHnterBLADE"

# ---------------------------------------------------------------------------
# Backlog games — ordered Z→A (inverse alphabetical) for insertion
# Games NOT owned yet (wishlist) are flagged below.
# ---------------------------------------------------------------------------

BACKLOG_Z_TO_A = [
    "Zone of the Enders: The 2nd Runner",
    "Zone of the Enders",
    "Yakuza Dead Souls",
    "XCOM: Enemy Unknown",
    "Wolfenstein: The New Order",
    "Vanquish",
    "Uncharted 3: Drake's Deception",
    "Uncharted 2: Among Thieves",
    "Uncharted: Drake's Fortune",
    "Tomb Raider",
    "Tom Clancy's Splinter Cell: Pandora Tomorrow HD",
    "Tom Clancy's Splinter Cell: Chaos Theory HD",
    "Tom Clancy's Splinter Cell HD",
    "Thief",
    "The Evil Within",
    "The Elder Scrolls V: Skyrim",
    "The Darkness II",
    "Sports Champions",
    "Splatterhouse",
    "Spec Ops: The Line",
    "South Park: The Stick of Truth",
    "Sly 3: Honor Among Thieves",
    "Sly 2: Band of Thieves",
    "Sly Cooper and the Thievius Raccoonus",
    "Sleeping Dogs",
    "Sherlock Holmes: Crimes & Punishments",
    "Shadows of the Damned",
    "Shadow of the Colossus",
    "Resistance 3",
    "Resident Evil 5",
    "Rayman Origins",
    "Ratchet & Clank: Up Your Arsenal",
    "Ratchet & Clank: Going Commando",
    "Ratchet & Clank",
    "Prototype 2",
    "Prototype",
    "Prince of Persia: Warrior Within HD",
    "Prince of Persia: The Two Thrones HD",
    "Prince of Persia Classic",
    "Ni No Kuni: Wrath of the White Witch",
    "Murdered: Soul Suspect",
    "Mirror's Edge",
    "Metro: Last Light",
    "Metal Gear Rising: Revengeance",
    "Metal Gear Solid 4: Guns of the Patriots",
    "Metal Gear Solid 3: Snake Eater HD",
    "Metal Gear Solid 2: Sons of Liberty HD",
    "Metal Gear Solid",
    "Medieval Moves: Deadmund's Quest",
    "Mass Effect 3",
    "Mass Effect 2",
    "Mass Effect",
    "Mafia II",
    "LEGO The Lord of the Rings",
    "L.A. Noire",
    "Kingdoms of Amalur: Reckoning",
    "Just Cause 2",
    "Jak 3",
    "Jak 2",
    "Jak and Daxter: The Precursor Legacy",
    "inFAMOUS 2",
    "inFAMOUS",
    "Ico",
    "Hotline Miami",
    "Hitman: Absolution",
    "Heavy Rain",
    "Gran Turismo 6",
    "God of War: Ghost of Sparta",
    "God of War: Chains of Olympus",
    "God of War III",
    "God of War II",
    "God of War",
    "Final Fantasy XIII-2",
    "Final Fantasy XIII",
    "Far Cry 3",
    "Fallout 3",
    "Dragon's Dogma",
    "Dragon Age: Origins",
    "Dishonored",
    "Devil May Cry 3: Dante's Awakening HD",
    "Devil May Cry 2 HD",
    "Devil May Cry HD",
    "Deus Ex: Human Revolution",
    "Demon's Souls",
    "Dead Space 2",
    "Dead Space",
    "Dead Island",
    "Dark Souls II",
    "Dark Souls",
    "Darksiders",
    "Call of Duty: Modern Warfare 3",
    "Call of Duty: Modern Warfare 2",
    "Borderlands",
    "BioShock Infinite",
    "BioShock 2",
    "BioShock",
    "Beyond: Two Souls",
    "Batman: Arkham City",
    "Batman: Arkham Asylum",
    "Assassin's Creed II",
    "Alien: Isolation",
]

# Games in the backlog that are NOT owned yet (wishlist status)
WISHLIST_TITLES = {
    "Alien: Isolation",
    "BioShock 2",
    "Dark Souls",
    "Dead Space",
    "Dead Space 2",
    "Dragon Age: Origins",
    "Final Fantasy XIII",
    "God of War: Chains of Olympus",
    "God of War: Ghost of Sparta",
    "God of War III",
    "Hotline Miami",
    "Ico",
    "inFAMOUS",
    "inFAMOUS 2",
    "Mafia II",
    "Metal Gear Solid 4: Guns of the Patriots",
    "Prince of Persia Classic",
    "Prince of Persia: The Two Thrones HD",
    "Prince of Persia: Warrior Within HD",
    "Prototype",
    "Ratchet & Clank",
    "Ratchet & Clank: Going Commando",
    "Ratchet & Clank: Up Your Arsenal",
    "Spec Ops: The Line",
}

# Games owned but platinum is unattainable — not added to backlog
UNATTAINABLE = [
    "Battlefield 3",
    "Call of Duty: Black Ops 2",
    "FIFA 09",
    "FIFA 12",
    "FIFA 13",
    "FIFA 15",
    "Killzone 2",
    "LittleBigPlanet",
    "LittleBigPlanet 2",
    "Mortal Kombat 9",
    "Mercenaries 2: World in Flames",
    "NBA 2K9",
    "Need for Speed: The Run",
    "SmackDown vs. Raw 2008",
    "Star Wars: The Force Unleashed",
]


BACKLOG_Z_TO_A = sorted(BACKLOG_Z_TO_A, key=str.lower, reverse=True)


def seed():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as n FROM games")
            existing = cur.fetchone()["n"]
            if existing > 0:
                print(f"DB already has {existing} games. Run with --force to reseed.")
                if "--force" not in sys.argv:
                    return

            if "--force" in sys.argv:
                cur.execute("DELETE FROM backlog_entries")
                cur.execute("DELETE FROM user_trophies")
                cur.execute("DELETE FROM trophies")
                cur.execute("DELETE FROM play_sessions")
                cur.execute("DELETE FROM user_games")
                cur.execute("DELETE FROM games")
                print("Cleared existing data.")

            print(f"Inserting {len(BACKLOG_Z_TO_A)} backlog games...")
            for pos, title in enumerate(BACKLOG_Z_TO_A, start=1):
                cur.execute("""
                    INSERT INTO games (title, platform)
                    VALUES (%s, 'PS3')
                    RETURNING id
                """, (title,))
                game_id = cur.fetchone()["id"]

                status = "wishlist" if title in WISHLIST_TITLES else "owned"
                cur.execute("""
                    INSERT INTO user_games (game_id, status, ownership)
                    VALUES (%s, %s, %s)
                """, (game_id, status, 'wanted' if status == 'wishlist' else 'owned'))

                cur.execute("""
                    INSERT INTO backlog_entries (game_id, position)
                    VALUES (%s, %s)
                """, (game_id, pos))

            print(f"Inserting {len(UNATTAINABLE)} unattainable games...")
            for title in UNATTAINABLE:
                cur.execute("""
                    INSERT INTO games (title, platform, platinum_feasibility, platinum_blocker_reason)
                    VALUES (%s, 'PS3', 'blocked', 'Legacy collection marks platinum unattainable; specific reason unverified')
                    RETURNING id
                """, (title,))
                game_id = cur.fetchone()["id"]
                cur.execute("""
                    INSERT INTO user_games (game_id, status)
                    VALUES (%s, 'owned')
                """, (game_id,))

            print("Done.")
            print(f"  Backlog: {len(BACKLOG_Z_TO_A)} games (Z→A order)")
            print(f"  Wishlist in backlog: {len(WISHLIST_TITLES)}")
            print(f"  Owned (unattainable, no backlog): {len(UNATTAINABLE)}")
            print(f"  PSN: {PSN_USERNAME}")


if __name__ == "__main__":
    seed()
