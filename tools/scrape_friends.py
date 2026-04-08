"""Scrape Friends transcripts from fangj.github.io and save as structured JSON.

Usage:
    python tools/scrape_friends.py

Output:
    resources/friends/transcripts.json
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

_BASE_URL = "https://fangj.github.io/friends/season/"

# (season, episode_or_range, title)
# episode_or_range: "101" or "212-213"
_EPISODES: list[tuple[int, str, str]] = [
    # Season 1
    (1, "101", "The One Where Monica Gets a Roommate"),
    (1, "102", "The One with the Sonogram at the End"),
    (1, "103", "The One with the Thumb"),
    (1, "104", "The One with George Stephanopoulos"),
    (1, "105", "The One with the East German Laundry Detergent"),
    (1, "106", "The One with the Butt"),
    (1, "107", "The One with the Blackout"),
    (1, "108", "The One Where Nana Dies Twice"),
    (1, "109", "The One Where Underdog Gets Away"),
    (1, "110", "The One with the Monkey"),
    (1, "111", "The One with Mrs. Bing"),
    (1, "112", "The One with the Dozen Lasagnas"),
    (1, "113", "The One with the Boobies"),
    (1, "114", "The One with the Candy Hearts"),
    (1, "115", "The One with the Stoned Guy"),
    (1, "116", "The One with Two Parts, Part 1"),
    (1, "117", "The One with Two Parts, Part 2"),
    (1, "118", "The One with All the Poker"),
    (1, "119", "The One Where the Monkey Gets Away"),
    (1, "120", "The One with the Evil Orthodontist"),
    (1, "121", "The One with the Fake Monica"),
    (1, "122", "The One with the Ick Factor"),
    (1, "123", "The One with the Birth"),
    (1, "124", "The One Where Rachel Finds Out"),
    # Season 2
    (2, "201", "The One with Ross's New Girlfriend"),
    (2, "202", "The One with the Breast Milk"),
    (2, "203", "The One Where Heckles Dies"),
    (2, "204", "The One with Phoebe's Husband"),
    (2, "205", "The One with Five Steaks and an Eggplant"),
    (2, "206", "The One with the Baby on the Bus"),
    (2, "207", "The One Where Ross Finds Out"),
    (2, "208", "The One with the List"),
    (2, "209", "The One with Phoebe's Dad"),
    (2, "210", "The One with Russ"),
    (2, "211", "The One with the Lesbian Wedding"),
    (2, "212-213", "The One After the Superbowl"),
    (2, "214", "The One with the Prom Video"),
    (2, "215", "The One Where Ross and Rachel... You Know"),
    (2, "216", "The One Where Joey Moves Out"),
    (2, "217", "The One Where Eddie Moves In"),
    (2, "218", "The One Where Dr. Ramoray Dies"),
    (2, "219", "The One Where Eddie Won't Go"),
    (2, "220", "The One Where Old Yeller Dies"),
    (2, "221", "The One with the Bullies"),
    (2, "222", "The One with Two Parties"),
    (2, "223", "The One with the Chicken Pox"),
    (2, "224", "The One with Barry and Mindy's Wedding"),
    # Season 3
    (3, "301", "The One with the Princess Leia Fantasy"),
    (3, "302", "The One Where No One's Ready"),
    (3, "303", "The One with the Jam"),
    (3, "304", "The One with the Metaphorical Tunnel"),
    (3, "305", "The One with Frank Jr."),
    (3, "306", "The One with the Flashback"),
    (3, "307", "The One with the Race Car Bed"),
    (3, "308", "The One with the Giant Poking Device"),
    (3, "309", "The One with the Football"),
    (3, "310", "The One Where Rachel Quits"),
    (3, "311", "The One Where Chandler Can't Remember Which Sister"),
    (3, "312", "The One with All the Jealousy"),
    (3, "313", "The One Where Monica and Richard Are Just Friends"),
    (3, "314", "The One with Phoebe's Ex-Partner"),
    (3, "315", "The One Where Ross and Rachel Take a Break"),
    (3, "316", "The One the Morning After"),
    (3, "317", "The One with the Ski Trip"),
    (3, "318", "The One with the Hypnosis Tape"),
    (3, "319", "The One with the Tiny T-Shirt"),
    (3, "320", "The One with the Dollhouse"),
    (3, "321", "The One with a Chick and a Duck"),
    (3, "322", "The One with the Screamer"),
    (3, "323", "The One with Ross's Thing"),
    (3, "324", "The One with the Ultimate Fighting Champion"),
    (3, "325", "The One at the Beach"),
    # Season 4
    (4, "401", "The One with the Jellyfish"),
    (4, "402", "The One with the Cat"),
    (4, "403", "The One with the Cuffs"),
    (4, "404", "The One with the Ballroom Dancing"),
    (4, "405", "The One with Joey's New Girlfriend"),
    (4, "406", "The One with the Dirty Girl"),
    (4, "407", "The One Where Chandler Crosses the Line"),
    (4, "408", "The One Where Chandler in a Box"),
    (4, "409", "The One Where They're Going to Party!"),
    (4, "410", "The One with the Girl from Poughkeepsie"),
    (4, "411", "The One with Phoebe's Uterus"),
    (4, "412", "The One with the Embryos"),
    (4, "413", "The One with Rachel's Crush"),
    (4, "414", "The One with Joey's Dirty Day"),
    (4, "415", "The One with All the Rugby"),
    (4, "416", "The One with the Fake Party"),
    (4, "417", "The One with the Free Porn"),
    (4, "418", "The One with Rachel's New Dress"),
    (4, "419", "The One with All the Haste"),
    (4, "420", "The One with All the Wedding Dresses"),
    (4, "421", "The One with the Invitation"),
    (4, "422", "The One with the Worst Best Man Ever"),
    (4, "423", "The One with Ross's Wedding"),
    # Season 5
    (5, "501", "The One with All the Resolutions"),
    (5, "502", "The One with All the Kissing"),
    (5, "503", "The One Hundredth"),
    (5, "504", "The One Where Phoebe Hates PBS"),
    (5, "505", "The One with the Kips"),
    (5, "506", "The One with the Yeti"),
    (5, "507", "The One Where Ross Moves In"),
    (5, "508", "The One with All the Thanksgivings"),
    (5, "509", "The One with Ross's Sandwich"),
    (5, "510", "The One with the Inappropriate Sister"),
    (5, "511", "The One with All the Resolutions"),
    (5, "512", "The One with Chandler's Work Laugh"),
    (5, "513", "The One with Joey's Bag"),
    (5, "514", "The One Where Everybody Finds Out"),
    (5, "515", "The One with the Girl Who Hits Joey"),
    (5, "516", "The One with the Cop"),
    (5, "517", "The One with Rachel's Inadvertent Kiss"),
    (5, "518", "The One Where Rachel Smokes"),
    (5, "519", "The One Where Ross Can't Flirt"),
    (5, "520", "The One with the Ride Along"),
    (5, "521", "The One with the Ball"),
    (5, "522", "The One with Joey's Big Break"),
    (5, "523", "The One in Vegas"),
    # Season 6
    (6, "601", "The One After Vegas"),
    (6, "602", "The One Where Ross Hugs Rachel"),
    (6, "603", "The One with Ross's Denial"),
    (6, "604", "The One Where Joey Loses His Insurance"),
    (6, "605", "The One with Joey's Porsche"),
    (6, "606", "The One on the Last Night"),
    (6, "607", "The One Where Phoebe Runs"),
    (6, "608", "The One with Ross's Teeth"),
    (6, "609", "The One Where Ross Got High"),
    (6, "610", "The One with the Routine"),
    (6, "611", "The One with the Apothecary Table"),
    (6, "612", "The One with the Joke"),
    (6, "613", "The One with Rachel's Sister"),
    (6, "614", "The One Where Chandler Can't Cry"),
    (6, "615-616", "The One That Could Have Been"),
    (6, "617", "The One with Unagi"),
    (6, "618", "The One Where Ross Dates a Student"),
    (6, "619", "The One with Joey's Fridge"),
    (6, "620", "The One with Mac and C.H.E.E.S.E."),
    (6, "621", "The One Where Ross Meets Elizabeth's Dad"),
    (6, "622", "The One Where Paul's the Man"),
    (6, "623", "The One with the Ring"),
    (6, "624", "The One with the Proposal"),
    # Season 7
    (7, "701", "The One with Monica's Thunder"),
    (7, "702", "The One with Rachel's Book"),
    (7, "703", "The One with Phoebe's Cookies"),
    (7, "704", "The One with Rachel's Assistant"),
    (7, "705", "The One with the Engagement Picture"),
    (7, "706", "The One with the Nap Partners"),
    (7, "707", "The One with Ross's Library Book"),
    (7, "708", "The One Where Chandler Doesn't Like Dogs"),
    (7, "709", "The One with All the Candy"),
    (7, "710", "The One with the Holiday Armadillo"),
    (7, "711", "The One with All the Cheesecakes"),
    (7, "712", "The One Where They're Up All Night"),
    (7, "713", "The One Where Rosita Dies"),
    (7, "714", "The One Where They All Turn Thirty"),
    (7, "715", "The One with Joey's New Brain"),
    (7, "716", "The One with the Truth About London"),
    (7, "717", "The One with the Cheap Wedding Dress"),
    (7, "718", "The One with Joey's Award"),
    (7, "719", "The One with Ross and Monica's Cousin"),
    (7, "720", "The One with Rachel's Big Kiss"),
    (7, "721", "The One with the Vows"),
    (7, "722", "The One with Chandler's Dad"),
    (7, "723", "The One with Chandler and Monica's Wedding"),
    (7, "724", "The One with Chandler and Monica's Wedding (Finale)"),
    # Season 8
    (8, "801", "The One After 'I Do'"),
    (8, "802", "The One with the Red Sweater"),
    (8, "803", "The One Where Rachel Tells..."),
    (8, "804", "The One with the Videotape"),
    (8, "805", "The One with Rachel's Date"),
    (8, "806", "The One with the Halloween Party"),
    (8, "807", "The One with the Stain"),
    (8, "808", "The One with the Stripper"),
    (8, "809", "The One with the Rumor"),
    (8, "810", "The One with Monica's Boots"),
    (8, "811", "The One with Ross's Step Forward"),
    (8, "812", "The One Where Joey Dates Rachel"),
    (8, "813", "The One Where Chandler Takes a Bath"),
    (8, "814", "The One with the Secret Closet"),
    (8, "815", "The One with the Birthing Video"),
    (8, "816", "The One Where Joey Tells Rachel"),
    (8, "817", "The One with the Tea Leaves"),
    (8, "818", "The One in Massapequa"),
    (8, "819", "The One with Joey's Interview"),
    (8, "820", "The One with the Baby Shower"),
    (8, "821", "The One with the Cooking Class"),
    (8, "822", "The One Where Rachel Is Late"),
    (8, "823", "The One Where Rachel Has a Baby"),
    # Season 9
    (9, "901", "The One Where No One Proposes"),
    (9, "902", "The One Where Emma Cries"),
    (9, "903", "The One with the Pediatrician"),
    (9, "904", "The One with the Sharks"),
    (9, "905", "The One with Phoebe's Birthday Dinner"),
    (9, "906", "The One with the Male Nanny"),
    (9, "907", "The One with Ross's Inappropriate Song"),
    (9, "908", "The One with Rachel's Other Sister"),
    (9, "909", "The One with Rachel's Phone Number"),
    (9, "910", "The One with Christmas in Tulsa"),
    (9, "911", "The One Where Rachel Goes Back to Work"),
    (9, "912", "The One with Phoebe's Rats"),
    (9, "913", "The One Where Monica Sings"),
    (9, "914", "The One with the Blind Dates"),
    (9, "915", "The One with the Mugging"),
    (9, "916", "The One with the Boob Job"),
    (9, "917", "The One with the Memorial Service"),
    (9, "918", "The One with the Lottery"),
    (9, "919", "The One with Rachel's Dream"),
    (9, "920", "The One with the Soap Opera Party"),
    (9, "921", "The One with the Fertility Test"),
    (9, "922", "The One with the Donor"),
    (9, "923-924", "The One in Barbados"),
    # Season 10
    (10, "1001", "The One After Joey and Rachel Kiss"),
    (10, "1002", "The One Where Ross Is Fine"),
    (10, "1003", "The One with Ross's Tan"),
    (10, "1004", "The One with the Cake"),
    (10, "1005", "The One Where Rachel's Sister Babysits"),
    (10, "1006", "The One with Ross's Grant"),
    (10, "1007", "The One with the Home Study"),
    (10, "1008", "The One with the Late Thanksgiving"),
    (10, "1009", "The One with the Birth Mother"),
    (10, "1010", "The One Where Chandler Gets Caught"),
    (10, "1011", "The One Where the Stripper Cries"),
    (10, "1012", "The One with Phoebe's Wedding"),
    (10, "1013", "The One Where Joey Speaks French"),
    (10, "1014", "The One with Princess Consuela"),
    (10, "1015", "The One Where Estelle Dies"),
    (10, "1016", "The One with Rachel's Going Away Party"),
    (10, "1017-1018", "The Last One"),
]

_RE_SCENE = re.compile(r"^\[Scene:\s*(.+?)]")
_RE_TIME_LAPSE = re.compile(r"^\[Time Lapse")
_RE_COMMERCIAL = re.compile(r"^\[Commercial")
_RE_CUT_TO = re.compile(r"^\[Cut to")
_RE_CLOSING = re.compile(r"^Closing|Closing Credits")
_RE_DIALOGUE = re.compile(r"^([A-Z][A-Za-z .'&]+?):\s*(.*)", re.DOTALL)
_RE_ACTION = re.compile(r"^\((.+?)\)$")
_RE_END = re.compile(r"^End$")
_RE_TAG = re.compile(r"<[^>]+>")
_RE_NBSP = re.compile(r"&nbsp;")
_RE_AMP = re.compile(r"&amp;")
_RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_RE_HR = re.compile(r"<hr[^>]*>", re.IGNORECASE)


def _episode_url(episode_code: str) -> str:
    """Convert episode code like '101' or '212-213' to URL filename.

    The website uses 4-digit codes with leading zero for seasons 1-9:
    season/0101.html, season/0901.html, season/1001.html
    """
    def _pad(code: str) -> str:
        return code if len(code) == 4 else f"0{code}"

    if "-" in episode_code:
        parts = episode_code.split("-")
        return f"{_pad(parts[0])}-{_pad(parts[1])}.html"
    return f"{_pad(episode_code)}.html"


def _parse_episode_number(episode_code: str) -> int:
    """Extract the primary episode number from code like '101' or '212-213'."""
    if "-" in episode_code:
        return int(episode_code.split("-")[1][-2:])
    code = episode_code[-2:]
    return int(code)


def _html_to_lines(raw_html: str) -> list[str]:
    """Convert HTML transcript to plain text lines.

    Handles two HTML formats:
    1. Each dialogue line in its own <p> tag with <b>Speaker:</b>
    2. Multiple lines in one <p> tag separated by <br>
    """
    # Extract body after second <hr> (after credits)
    hr_positions = [m.end() for m in _RE_HR.finditer(raw_html)]
    if len(hr_positions) >= 2:
        body = raw_html[hr_positions[1]:]
    else:
        body = raw_html

    # Replace <br> with newlines
    body = _RE_BR.sub("\n", body)

    # Strip all HTML tags
    body = _RE_TAG.sub("", body)

    # Decode HTML entities
    body = _RE_NBSP.sub(" ", body)
    body = _RE_AMP.sub("&", body)

    # Split into lines and normalize whitespace
    lines: list[str] = []
    for line in body.split("\n"):
        line = " ".join(line.split()).strip()
        if line:
            lines.append(line)
    return lines


def parse_transcript(raw_html: str) -> list[dict]:
    """Parse raw HTML transcript into list of scenes."""
    lines = _html_to_lines(raw_html)

    scenes: list[dict] = []
    current_scene: dict | None = None

    for text in lines:
        if not text:
            continue

        if _RE_END.match(text):
            break

        if _RE_CLOSING.match(text):
            break

        # Scene header
        m = _RE_SCENE.match(text)
        if m:
            if current_scene:
                scenes.append(current_scene)
            current_scene = {"location": m.group(1).strip(), "lines": []}
            continue

        # Scene transitions
        if _RE_TIME_LAPSE.match(text) or _RE_COMMERCIAL.match(text) or _RE_CUT_TO.match(text):
            if current_scene:
                current_scene["lines"].append({"speaker": "", "text": text})
            continue

        if current_scene is None:
            current_scene = {"location": "", "lines": []}

        # Dialogue line
        m = _RE_DIALOGUE.match(text)
        if m:
            speaker = m.group(1).strip()
            dialogue = m.group(2).strip()
            current_scene["lines"].append({"speaker": speaker, "text": dialogue})
            continue

        # Action/stage direction
        m = _RE_ACTION.match(text)
        if m:
            current_scene["lines"].append({"speaker": "", "text": text})
            continue

        # Other text
        current_scene["lines"].append({"speaker": "", "text": text})

    if current_scene:
        scenes.append(current_scene)

    return scenes


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    output_path = project_root / "resources" / "friends" / "transcripts.json"

    client = httpx.Client(timeout=30.0, follow_redirects=True)
    episodes: list[dict] = []
    errors: list[str] = []

    for season, episode_code, title in _EPISODES:
        url = f"{_BASE_URL}{_episode_url(episode_code)}"
        episode_num = _parse_episode_number(episode_code)
        print(f"Fetching S{season:02d}E{episode_num:02d} ({title})...", end=" ", flush=True)

        try:
            resp = client.get(url)
            resp.raise_for_status()
            scenes = parse_transcript(resp.text)
            dialogue_count = sum(
                1 for s in scenes for line in s["lines"] if line["speaker"]
            )
            print(f"OK ({len(scenes)} scenes, {dialogue_count} lines)")
            episodes.append({
                "season": season,
                "episode": episode_num,
                "title": title,
                "scenes": scenes,
            })
        except Exception as e:
            print(f"FAILED: {e}")
            errors.append(f"S{season:02d}E{episode_num:02d}: {e}")

        time.sleep(0.3)

    client.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(episodes)} episodes to {output_path}")
    if errors:
        print(f"\n{len(errors)} errors:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
