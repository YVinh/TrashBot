"""Generate location-based hashtags and relevant X accounts to mention."""

def get_location_from_coords(latitude: float, longitude: float) -> str:
    """
    Determine location name from coordinates.

    Args:
        latitude: Latitude coordinate
        longitude: Longitude coordinate

    Returns:
        Location name as string
    """
    # Saint-Josse-ten-Noode: Belgium's smallest commune (~1.1 km²), centered
    # on 50.853°N, 4.372°E — checked before the wider Brussels box below since
    # it's fully contained within it.
    if 50.848 <= latitude <= 50.858 and 4.365 <= longitude <= 4.380:
        return "SaintJosse"
    # Brussels area: 50.85°N, 4.35°E
    elif 50.7 <= latitude <= 50.9 and 4.2 <= longitude <= 4.5:
        return "Brussels"
    # Amsterdam area
    elif 52.3 <= latitude <= 52.4 and 4.8 <= longitude <= 5.0:
        return "Amsterdam"
    # Antwerp area
    elif 51.2 <= latitude <= 51.3 and 4.3 <= longitude <= 4.5:
        return "Antwerp"
    # Add more as needed
    else:
        return "Europe"

def generate_hashtags(location: str, object_type: str = "trash") -> list:
    """
    Generate relevant hashtags based on location and content type.

    Args:
        location: Location name
        object_type: Type of litter (trash, plastic, etc)

    Returns:
        List of hashtags
    """
    # Universal environmental hashtags (French)
    universal_tags = [
        "#ActionClimatique",
        "#AlerteDéchets",
        "#PropretéUrbaine",
        "#AgirPourLeClimat",
        "#GrèvePourLeClimat",
    ]

    # Location-specific hashtags (French). For Brussels, #bruxellespropreté and
    # #netbrussel are the real hashtags Bruxelles-Propreté's own official
    # Instagram actually uses (verified directly —
    # https://www.instagram.com/bruxellesproprete_netbrussel/); #brugov and
    # #réformerBruxelles were supplied directly by the project owner from
    # their own browsing, not independently re-verified here. SaintJosse gets
    # its own commune-specific tag when GPS resolves that precisely.
    location_tags = {
        "SaintJosse": ["#SaintJosseNews"],
        "Brussels": [
            "#bruxellespropreté",
            "#netbrussel",
            "#brugov",
            "#réformerBruxelles",
            "#Bruxelles",
            "#BXL",
            "#VilleDeBruxelles",
            "#Bruxellois",
        ],
        "Amsterdam": ["#Amsterdam", "#AMS", "#VilleAmsterdam"],
        "Antwerp": ["#Anvers", "#Antwerpen", "#VilleAnvers"],
        "Europe": ["#VillesEuropéennes"],
    }

    # SaintJosse is a specific commune within Brussels — always add the
    # regional tags too so it isn't limited to just the one local tag.
    if location == "SaintJosse":
        tags = location_tags["SaintJosse"] + location_tags["Brussels"]
        tags.extend(universal_tags)
        return tags

    # Location-specific first so callers that slice the top N don't lose them
    # under the generic universal tags.
    tags = location_tags.get(location, []).copy()
    tags.extend(universal_tags)

    return tags

def get_mentions_for_location(location: str) -> list:
    """
    Get relevant X accounts to mention based on location.

    Args:
        location: Location name

    Returns:
        List of X handles to mention (without @ prefix)
    """
    mentions = {
        "Brussels": [
            "BrusselsCity",  # City of Brussels
            "brussels_faq",  # Brussels info
            "IBGE_Bruxelles",  # Brussels regional government
            "GreenpeaceBE",  # Environmental org
            "WWF_BE",  # World Wildlife Fund Belgium
            "ClientEarth_Org",  # Environmental org
        ],
        "Amsterdam": [
            "Gemeente_AMS",
            "EB_Amsterdam",
            "GreenpeaceNL",
            "WWF_NL",
        ],
        "Antwerp": [
            "StadAntwerpen",
            "BVO_Antwerpen",
            "GreenpeaceBE",
            "WWF_BE",
        ],
        "Europe": [
            "GreenpeaceEU",
            "EU_ENV",
            "UNEP",  # UN Environment Programme
        ],
    }

    return mentions.get(location, mentions["Europe"])

def format_mentions(mentions: list) -> str:
    """
    Format mentions as X-compatible string with @ prefix.

    Args:
        mentions: List of handles

    Returns:
        String of mentions separated by space
    """
    return " ".join([f"@{handle}" for handle in mentions])

def format_hashtags(hashtags: list) -> str:
    """
    Format hashtags as X-compatible string.

    Args:
        hashtags: List of hashtag strings (with or without #)

    Returns:
        String of hashtags separated by space
    """
    formatted = []
    for tag in hashtags:
        if not tag.startswith("#"):
            tag = f"#{tag}"
        formatted.append(tag)
    return " ".join(formatted)
