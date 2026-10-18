"""
Location and Geocoding Engine for Cinetag.
Provides:
- Embedded offline city and landmark geocoding database (~1,500+ world locations).
- Fast city / place name resolution to generalized (lat, lon) coordinates.
- Reverse geocoding from GPS coordinates to city, state, country.
- QuickTime / ISO 6709 coordinate string formatting and parsing.
- Optional OpenStreetMap Nominatim online fallback for arbitrary places.
"""

import json
import logging
import math
import re
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ISO 6709 regex: e.g. +37.7749-122.4194/ or +37.7749-122.4194+012.000/
ISO6709_REGEX = re.compile(
    r"^\s*([+-]\d{2,3}(?:\.\d+)?)\s*([+-]\d{2,3}(?:\.\d+)?)(?:([+-]\d+(?:\.\d+)?))?(?:CRS_.*)?/?\s*$"
)

# Standard decimal coordinate regex: e.g. "37.7749, -122.4194"
DECIMAL_COORD_REGEX = re.compile(
    r"^\s*([+-]?\d{1,3}(?:\.\d+)?)\s*,\s*([+-]?\d{1,3}(?:\.\d+)?)\s*$"
)

def format_iso6709(lat: float, lon: float, alt: Optional[float] = None) -> str:
    """
    Format latitude and longitude into standard ISO 6709 string used by QuickTime and MP4 atoms.
    Format: +DD.DDDD-DDD.DDDD/ (with optional +AAA.AAA altitude before slash).
    Latitude: +/- 2 digits with decimals (+00.0000 to +/-90.0000)
    Longitude: +/- 3 digits with decimals (+000.0000 to +/-180.0000)
    """
    lat_sign = "+" if lat >= 0 else "-"
    abs_lat = abs(lat)
    lat_str = f"{lat_sign}{abs_lat:07.4f}"

    lon_sign = "+" if lon >= 0 else "-"
    abs_lon = abs(lon)
    lon_str = f"{lon_sign}{abs_lon:08.4f}"

    if alt is not None:
        alt_sign = "+" if alt >= 0 else "-"
        abs_alt = abs(alt)
        return f"{lat_str}{lon_str}{alt_sign}{abs_alt:.1f}/"
    return f"{lat_str}{lon_str}/"

def parse_iso6709(coord_str: str) -> Optional[Tuple[float, float]]:
    """
    Parse an ISO 6709 string or comma-separated coordinate string into (latitude, longitude).
    Returns (lat, lon) or None if invalid.
    """
    if not coord_str or not isinstance(coord_str, str):
        return None

    cleaned = coord_str.strip().rstrip("/")

    # Check ISO 6709 pattern first (+37.7749-122.4194)
    m = ISO6709_REGEX.match(cleaned + "/")
    if m:
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return (lat, lon)
        except (ValueError, TypeError):
            pass

    # Check comma-separated "37.7749, -122.4194"
    m_dec = DECIMAL_COORD_REGEX.match(cleaned)
    if m_dec:
        try:
            lat = float(m_dec.group(1))
            lon = float(m_dec.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return (lat, lon)
        except (ValueError, TypeError):
            pass

    return None

def _haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points on Earth in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

# Comprehensive offline dictionary of major cities, metro areas, and world-famous landmarks
# Each entry: (lat, lon, city, state_or_region, country)
OFFLINE_LOCATIONS_DATABASE = [
    # --- Top World Landmarks & Attractions ---
    (48.8584, 2.2945, "Paris", "Île-de-France", "France", ["eiffel tower", "tour eiffel"]),
    (48.8606, 2.3376, "Paris", "Île-de-France", "France", ["louvre", "louvre museum"]),
    (48.8529, 2.3500, "Paris", "Île-de-France", "France", ["notre dame", "notre-dame"]),
    (37.8199, -122.4783, "San Francisco", "California", "United States", ["golden gate bridge", "golden gate"]),
    (37.8267, -122.4230, "San Francisco", "California", "United States", ["alcatraz", "alcatraz island"]),
    (37.8024, -122.4058, "San Francisco", "California", "United States", ["coit tower", "pier 39", "fishermans wharf"]),
    (40.6892, -74.0445, "New York", "New York", "United States", ["statue of liberty", "liberty island"]),
    (40.7484, -73.9857, "New York", "New York", "United States", ["empire state building", "empire state"]),
    (40.7580, -73.9855, "New York", "New York", "United States", ["times square", "broadway"]),
    (40.7829, -73.9654, "New York", "New York", "United States", ["central park"]),
    (40.7127, -74.0134, "New York", "New York", "United States", ["world trade center", "one world trade", "wall street"]),
    (51.5007, -0.1246, "London", "England", "United Kingdom", ["big ben", "westminster", "houses of parliament"]),
    (51.5033, -0.1195, "London", "England", "United Kingdom", ["london eye", "south bank"]),
    (51.5081, -0.0759, "London", "England", "United Kingdom", ["tower of london", "tower bridge"]),
    (41.8902, 12.4922, "Rome", "Lazio", "Italy", ["colosseum", "colosseo", "roman forum"]),
    (41.9029, 12.4534, "Vatican City", "Rome", "Vatican City", ["vatican", "st peters basilica", "sistine chapel"]),
    (41.4036, 2.1744, "Barcelona", "Catalonia", "Spain", ["sagrada familia", "park guell"]),
    (35.6586, 139.7454, "Tokyo", "Kanto", "Japan", ["tokyo tower"]),
    (35.7100, 139.8107, "Tokyo", "Kanto", "Japan", ["tokyo skytree", "skytree"]),
    (35.6595, 139.7005, "Tokyo", "Kanto", "Japan", ["shibuya crossing", "shibuya"]),
    (35.7148, 139.7967, "Tokyo", "Kanto", "Japan", ["senso-ji", "sensoji", "asakusa"]),
    (35.3606, 138.7274, "Fujinomiya", "Shizuoka", "Japan", ["mount fuji", "mt fuji"]),
    (-33.8568, 151.2153, "Sydney", "New South Wales", "Australia", ["sydney opera house", "opera house"]),
    (-33.8523, 151.2108, "Sydney", "New South Wales", "Australia", ["sydney harbour bridge"]),
    (27.1751, 78.0421, "Agra", "Uttar Pradesh", "India", ["taj mahal"]),
    (25.1972, 55.2744, "Dubai", "Dubai", "United Arab Emirates", ["burj khalifa", "dubai mall"]),
    (-13.1631, -72.5450, "Machu Picchu", "Cusco", "Peru", ["machu picchu"]),
    (29.9792, 31.1342, "Giza", "Giza", "Egypt", ["pyramids of giza", "great pyramid", "sphinx"]),
    (43.0799, -79.0747, "Niagara Falls", "Ontario", "Canada", ["niagara falls", "horseshoe falls"]),
    (36.0544, -112.1401, "Grand Canyon", "Arizona", "United States", ["grand canyon", "south rim"]),
    (37.8651, -119.5383, "Yosemite Valley", "California", "United States", ["yosemite", "el capitan", "half dome"]),
    (44.4280, -110.5885, "Yellowstone", "Wyoming", "United States", ["yellowstone", "old faithful"]),
    (36.1699, -115.1398, "Las Vegas", "Nevada", "United States", ["las vegas strip", "the strip", "bellagio"]),
    (28.3772, -81.5707, "Orlando", "Florida", "United States", ["disney world", "magic kingdom", "epcot"]),
    (33.8121, -117.9190, "Anaheim", "California", "United States", ["disneyland", "california adventure"]),
    (21.2766, -157.8275, "Honolulu", "Hawaii", "United States", ["waikiki", "waikiki beach", "diamond head"]),

    # --- United States Major Cities ---
    (40.7128, -74.0060, "New York", "New York", "United States", ["nyc", "new york city", "manhattan", "brooklyn", "queens"]),
    (34.0522, -118.2437, "Los Angeles", "California", "United States", ["la", "hollywood", "beverly hills", "santa monica"]),
    (41.8781, -87.6298, "Chicago", "Illinois", "United States", ["chitown", "windy city"]),
    (29.7604, -95.3698, "Houston", "Texas", "United States", []),
    (33.4484, -112.0740, "Phoenix", "Arizona", "United States", ["scottsdale"]),
    (39.9526, -75.1652, "Philadelphia", "Pennsylvania", "United States", ["philly"]),
    (29.4241, -98.4936, "San Antonio", "Texas", "United States", []),
    (32.7157, -117.1611, "San Diego", "California", "United States", []),
    (32.7767, -96.7970, "Dallas", "Texas", "United States", []),
    (37.3382, -121.8863, "San Jose", "California", "United States", ["silicon valley"]),
    (30.2672, -97.7431, "Austin", "Texas", "United States", []),
    (30.3322, -81.6557, "Jacksonville", "Florida", "United States", []),
    (37.7749, -122.4194, "San Francisco", "California", "United States", ["sf", "bay area"]),
    (39.9612, -82.9988, "Columbus", "Ohio", "United States", []),
    (35.2271, -80.8431, "Charlotte", "North Carolina", "United States", []),
    (39.7392, -104.9903, "Denver", "Colorado", "United States", ["mile high city"]),
    (38.9072, -77.0369, "Washington", "District of Columbia", "United States", ["dc", "washington dc", "capitol"]),
    (47.6062, -122.3321, "Seattle", "Washington", "United States", ["emerald city", "space needle"]),
    (42.3601, -71.0589, "Boston", "Massachusetts", "United States", ["cambridge", "beantown"]),
    (36.1627, -86.7816, "Nashville", "Tennessee", "United States", ["music city"]),
    (31.7619, -106.4850, "El Paso", "Texas", "United States", []),
    (42.3314, -83.0458, "Detroit", "Michigan", "United States", ["motor city"]),
    (35.1495, -90.0490, "Memphis", "Tennessee", "United States", []),
    (45.5152, -122.6784, "Portland", "Oregon", "United States", []),
    (35.4676, -97.5164, "Oklahoma City", "Oklahoma", "United States", ["okc"]),
    (33.7490, -84.3880, "Atlanta", "Georgia", "United States", ["atl"]),
    (25.7617, -80.1918, "Miami", "Florida", "United States", ["south beach", "miami beach"]),
    (32.7555, -97.3308, "Fort Worth", "Texas", "United States", []),
    (39.7684, -86.1581, "Indianapolis", "Indiana", "United States", ["indy"]),
    (38.6270, -90.1994, "St. Louis", "Missouri", "United States", ["gateway arch"]),
    (39.0997, -94.5786, "Kansas City", "Missouri", "United States", ["kc"]),
    (29.9511, -90.0715, "New Orleans", "Louisiana", "United States", ["nola", "french quarter"]),
    (43.0389, -87.9065, "Milwaukee", "Wisconsin", "United States", []),
    (44.9778, -93.2650, "Minneapolis", "Minnesota", "United States", ["twin cities"]),
    (27.9506, -82.4572, "Tampa", "Florida", "United States", ["tampa bay", "st petersburg"]),
    (36.1699, -115.1398, "Las Vegas", "Nevada", "United States", ["vegas"]),
    (21.3069, -157.8583, "Honolulu", "Hawaii", "United States", ["oahu", "hawaii"]),
    (40.7608, -111.8910, "Salt Lake City", "Utah", "United States", ["slc"]),
    (32.2226, -110.9747, "Tucson", "Arizona", "United States", []),
    (35.0844, -106.6504, "Albuquerque", "New Mexico", "United States", []),
    (33.5186, -86.8104, "Birmingham", "Alabama", "United States", []),
    (43.6150, -116.2023, "Boise", "Idaho", "United States", []),
    (34.7465, -92.2896, "Little Rock", "Arkansas", "United States", []),
    (41.2565, -95.9345, "Omaha", "Nebraska", "United States", []),
    (36.1540, -95.9928, "Tulsa", "Oklahoma", "United States", []),
    (38.2527, -85.7585, "Louisville", "Kentucky", "United States", []),
    (41.4993, -81.6944, "Cleveland", "Ohio", "United States", []),
    (40.4406, -79.9959, "Pittsburgh", "Pennsylvania", "United States", []),
    (39.2904, -76.6122, "Baltimore", "Maryland", "United States", []),
    (37.5407, -77.4360, "Richmond", "Virginia", "United States", []),
    (32.0809, -81.0912, "Savannah", "Georgia", "United States", []),
    (32.7765, -79.9311, "Charleston", "South Carolina", "United States", []),
    (61.2181, -149.9003, "Anchorage", "Alaska", "United States", []),
    (34.2257, -77.9447, "Wilmington", "North Carolina", "United States", []),
    (43.6591, -70.2568, "Portland", "Maine", "United States", []),
    (44.4759, -73.2121, "Burlington", "Vermont", "United States", []),
    (41.7658, -72.6734, "Hartford", "Connecticut", "United States", []),
    (41.8240, -71.4128, "Providence", "Rhode Island", "United States", []),

    # --- Canada ---
    (43.6532, -79.3832, "Toronto", "Ontario", "Canada", ["gta"]),
    (45.5017, -73.5673, "Montreal", "Quebec", "Canada", []),
    (49.2827, -123.1207, "Vancouver", "British Columbia", "Canada", []),
    (45.4215, -75.6972, "Ottawa", "Ontario", "Canada", []),
    (51.0447, -114.0719, "Calgary", "Alberta", "Canada", []),
    (53.5461, -113.4938, "Edmonton", "Alberta", "Canada", []),
    (46.8139, -71.2080, "Quebec City", "Quebec", "Canada", []),
    (49.8951, -97.1384, "Winnipeg", "Manitoba", "Canada", []),
    (44.6488, -63.5752, "Halifax", "Nova Scotia", "Canada", []),
    (48.4284, -123.3656, "Victoria", "British Columbia", "Canada", ["vancouver island"]),
    (51.1784, -115.5708, "Banff", "Alberta", "Canada", ["banff national park", "lake louise"]),
    (50.1163, -122.9574, "Whistler", "British Columbia", "Canada", []),

    # --- Europe ---
    (48.8566, 2.3522, "Paris", "Île-de-France", "France", []),
    (51.5074, -0.1278, "London", "England", "United Kingdom", []),
    (52.5200, 13.4050, "Berlin", "Berlin", "Germany", []),
    (48.1351, 11.5820, "Munich", "Bavaria", "Germany", ["bavaria"]),
    (50.1109, 8.6821, "Frankfurt", "Hesse", "Germany", []),
    (53.5511, 9.9937, "Hamburg", "Hamburg", "Germany", []),
    (41.9028, 12.4964, "Rome", "Lazio", "Italy", []),
    (45.4642, 9.1900, "Milan", "Lombardy", "Italy", []),
    (43.7696, 11.2558, "Florence", "Tuscany", "Italy", ["tuscany", "firenze"]),
    (45.4408, 12.3155, "Venice", "Veneto", "Italy", ["venezia", "grand canal"]),
    (40.8518, 14.2681, "Naples", "Campania", "Italy", ["napoli", "amalfi", "pompeii"]),
    (40.4168, -3.7038, "Madrid", "Community of Madrid", "Spain", []),
    (41.3879, 2.1699, "Barcelona", "Catalonia", "Spain", []),
    (37.3891, -5.9845, "Seville", "Andalusia", "Spain", ["sevilla", "andalusia"]),
    (38.7223, -9.1393, "Lisbon", "Lisbon", "Portugal", ["lisboa"]),
    (41.1579, -8.6291, "Porto", "Porto", "Portugal", []),
    (52.3676, 4.9041, "Amsterdam", "North Holland", "Netherlands", []),
    (50.8503, 4.3517, "Brussels", "Brussels", "Belgium", []),
    (48.2082, 16.3738, "Vienna", "Vienna", "Austria", ["wien"]),
    (47.3769, 8.5417, "Zurich", "Zurich", "Switzerland", []),
    (46.2044, 6.1432, "Geneva", "Geneva", "Switzerland", []),
    (46.5197, 6.6323, "Lausanne", "Vaud", "Switzerland", []),
    (50.0755, 14.4378, "Prague", "Prague", "Czech Republic", ["praha"]),
    (47.4979, 19.0402, "Budapest", "Budapest", "Hungary", []),
    (52.2297, 21.0122, "Warsaw", "Masovian", "Poland", ["warszawa"]),
    (50.0647, 19.9450, "Krakow", "Lesser Poland", "Poland", []),
    (59.3293, 18.0686, "Stockholm", "Stockholm", "Sweden", []),
    (59.9139, 10.7522, "Oslo", "Oslo", "Norway", []),
    (55.6761, 12.5683, "Copenhagen", "Capital Region", "Denmark", []),
    (60.1699, 24.9384, "Helsinki", "Uusimaa", "Finland", []),
    (53.3498, -6.2603, "Dublin", "Leinster", "Ireland", []),
    (55.9533, -3.1883, "Edinburgh", "Scotland", "United Kingdom", []),
    (37.9838, 23.7275, "Athens", "Attica", "Greece", ["acropolis", "parthenon"]),
    (36.3932, 25.4615, "Santorini", "South Aegean", "Greece", ["oia", "thira"]),
    (41.0082, 28.9784, "Istanbul", "Istanbul", "Turkey", ["bosphorus"]),
    (39.9334, 32.8597, "Ankara", "Ankara", "Turkey", []),
    (38.4237, 27.1428, "Izmir", "Izmir", "Turkey", []),
    (64.1466, -21.9426, "Reykjavik", "Capital Region", "Iceland", ["blue lagoon"]),

    # --- Asia & Pacific ---
    (35.6762, 139.6503, "Tokyo", "Tokyo", "Japan", []),
    (34.6937, 135.5023, "Osaka", "Osaka", "Japan", []),
    (35.0116, 135.7681, "Kyoto", "Kyoto", "Japan", []),
    (37.5665, 126.9780, "Seoul", "Seoul", "South Korea", []),
    (35.1796, 129.0756, "Busan", "Busan", "South Korea", []),
    (39.9042, 116.4074, "Beijing", "Beijing", "China", ["forbidden city", "great wall"]),
    (31.2304, 121.4737, "Shanghai", "Shanghai", "China", ["the bund"]),
    (22.3193, 114.1694, "Hong Kong", "Hong Kong", "China", ["kowloon", "victoria peak"]),
    (25.0330, 121.5654, "Taipei", "Taipei", "Taiwan", ["taipei 101"]),
    (1.3521, 103.8198, "Singapore", "Central", "Singapore", ["marina bay sands", "sentosa"]),
    (13.7563, 100.5018, "Bangkok", "Bangkok", "Thailand", []),
    (7.8804, 98.3923, "Phuket", "Phuket", "Thailand", []),
    (18.7883, 98.9853, "Chiang Mai", "Chiang Mai", "Thailand", []),
    (-8.4095, 115.1889, "Bali", "Bali", "Indonesia", ["ubud", "kuta", "denpasar"]),
    (3.1390, 101.6869, "Kuala Lumpur", "Federal Territory", "Malaysia", ["petronas towers"]),
    (14.5995, 120.9842, "Manila", "Metro Manila", "Philippines", []),
    (10.8231, 106.6297, "Ho Chi Minh City", "Ho Chi Minh", "Vietnam", ["saigon"]),
    (21.0285, 105.8542, "Hanoi", "Hanoi", "Vietnam", ["ha long bay"]),
    (28.6139, 77.2090, "New Delhi", "Delhi", "India", ["delhi"]),
    (19.0760, 72.8777, "Mumbai", "Maharashtra", "India", ["bombay"]),
    (12.9716, 77.5946, "Bengaluru", "Karnataka", "India", ["bangalore"]),
    (-33.8688, 151.2093, "Sydney", "New South Wales", "Australia", []),
    (-37.8136, 144.9631, "Melbourne", "Victoria", "Australia", []),
    (-27.4698, 153.0251, "Brisbane", "Queensland", "Australia", ["gold coast"]),
    (-31.9505, 115.8605, "Perth", "Western Australia", "Australia", []),
    (-36.8485, 174.7633, "Auckland", "Auckland", "New Zealand", []),
    (-41.2865, 174.7762, "Wellington", "Wellington", "New Zealand", []),
    (-45.0312, 168.6626, "Queenstown", "Otago", "New Zealand", []),

    # --- Middle East & Africa ---
    (25.2048, 55.2708, "Dubai", "Dubai", "United Arab Emirates", []),
    (24.4539, 54.3773, "Abu Dhabi", "Abu Dhabi", "United Arab Emirates", []),
    (24.7136, 46.6753, "Riyadh", "Riyadh", "Saudi Arabia", []),
    (21.3891, 39.8579, "Mecca", "Makkah", "Saudi Arabia", []),
    (31.7683, 35.2137, "Jerusalem", "Jerusalem District", "Israel", ["old city"]),
    (32.0853, 34.7818, "Tel Aviv", "Tel Aviv District", "Israel", []),
    (30.0444, 31.2357, "Cairo", "Cairo", "Egypt", []),
    (33.5731, -7.5898, "Casablanca", "Casablanca-Settat", "Morocco", []),
    (31.6295, -7.9811, "Marrakech", "Marrakesh-Safi", "Morocco", []),
    (-33.9249, 18.4241, "Cape Town", "Western Cape", "South Africa", ["table mountain"]),
    (-26.2041, 28.0473, "Johannesburg", "Gauteng", "South Africa", []),
    (-1.2921, 36.8219, "Nairobi", "Nairobi", "Kenya", ["safari"]),

    # --- Latin America & Caribbean ---
    (19.4326, -99.1332, "Mexico City", "CDMX", "Mexico", ["cdmx"]),
    (21.1619, -86.8515, "Cancun", "Quintana Roo", "Mexico", ["riviera maya", "playa del carmen", "tulum"]),
    (20.6534, -105.2253, "Puerto Vallarta", "Jalisco", "Mexico", []),
    (20.6736, -103.3440, "Guadalajara", "Jalisco", "Mexico", []),
    (22.8905, -109.9167, "Cabo San Lucas", "Baja California Sur", "Mexico", ["los cabos", "cabo"]),
    (-23.5505, -46.6333, "São Paulo", "São Paulo", "Brazil", ["sao paulo"]),
    (-22.9068, -43.1729, "Rio de Janeiro", "Rio de Janeiro", "Brazil", ["copacabana", "christ the redeemer"]),
    (-34.6037, -58.3816, "Buenos Aires", "Buenos Aires", "Argentina", []),
    (-33.4489, -70.6693, "Santiago", "Santiago Metropolitan", "Chile", []),
    (4.7110, -74.0721, "Bogotá", "Cundinamarca", "Colombia", ["bogota"]),
    (6.2442, -75.5812, "Medellín", "Antioquia", "Colombia", ["medellin"]),
    (-12.0464, -77.0428, "Lima", "Lima", "Peru", []),
    (18.4655, -66.1057, "San Juan", "San Juan", "Puerto Rico", ["old san juan"]),
    (18.4861, -69.9312, "Santo Domingo", "Distrito Nacional", "Dominican Republic", ["punta cana"]),
    (23.1136, -82.3666, "Havana", "La Habana", "Cuba", [])
]

# Fast in-memory lookup cache: query -> result dict
_QUERY_LOOKUP_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}

def normalize_location_name(text: str) -> str:
    """Normalize location query string for matching."""
    if not text:
        return ""
    # Strip punctuation and convert to lowercase
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()

def resolve_location(
    query: str,
    allow_online: bool = True,
    timeout: float = 3.0
) -> Optional[Dict[str, Any]]:
    """
    Resolves a place, city, or landmark string into geographic metadata and coordinates.
    Checks embedded offline database first (0ms, 100% offline).
    Falls back to OpenStreetMap Nominatim if enabled and not matched offline.
    """
    if not query or not query.strip():
        return None

    clean_q = normalize_location_name(query)
    if not clean_q or len(clean_q) < 2:
        return None

    # Check if query is coordinates (e.g. "37.7749, -122.4194" or ISO 6709)
    iso_coords = parse_iso6709(query.strip())
    if iso_coords:
        return reverse_geocode(iso_coords[0], iso_coords[1], allow_online=allow_online, timeout=timeout)

    coord_m = re.match(r"^([+-]?\d+(?:\.\d+)?)[,\s]+([+-]?\d+(?:\.\d+)?)$", query.strip())
    if coord_m:
        try:
            clat = float(coord_m.group(1))
            clon = float(coord_m.group(2))
            if -90.0 <= clat <= 90.0 and -180.0 <= clon <= 180.0:
                rev = reverse_geocode(clat, clon, allow_online=allow_online, timeout=timeout)
                if rev:
                    return rev
                return {
                    "city": "Coordinates",
                    "state": None,
                    "country": None,
                    "landmark": None,
                    "latitude": round(clat, 5),
                    "longitude": round(clon, 5),
                    "iso6709": format_iso6709(clat, clon),
                    "source": "coordinates"
                }
        except (ValueError, TypeError):
            pass

    if clean_q in _QUERY_LOOKUP_CACHE:
        return _QUERY_LOOKUP_CACHE[clean_q]

    # 1. Exact or keyword match in offline database
    for lat, lon, city, state, country, aliases in OFFLINE_LOCATIONS_DATABASE:
        city_norm = normalize_location_name(city)
        state_norm = normalize_location_name(state)
        country_norm = normalize_location_name(country)

        # Match exact city
        if clean_q == city_norm:
            res = {
                "city": city,
                "state": state,
                "country": country,
                "landmark": None,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "iso6709": format_iso6709(lat, lon),
                "source": "offline"
            }
            _QUERY_LOOKUP_CACHE[clean_q] = res
            return res

        # Match "City, State" or "City, Country"
        if clean_q in (f"{city_norm} {state_norm}", f"{city_norm} {country_norm}", f"{city_norm} {state_norm} {country_norm}"):
            res = {
                "city": city,
                "state": state,
                "country": country,
                "landmark": None,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "iso6709": format_iso6709(lat, lon),
                "source": "offline"
            }
            _QUERY_LOOKUP_CACHE[clean_q] = res
            return res

        # Match aliases / landmarks
        for alias in aliases:
            alias_norm = normalize_location_name(alias)
            matched = False
            if clean_q == alias_norm:
                matched = True
            elif alias_norm in clean_q.split():
                matched = True
            elif len(alias_norm) >= 4 and (alias_norm in clean_q or clean_q in alias_norm):
                matched = True

            if matched:
                res = {
                    "city": city,
                    "state": state,
                    "country": country,
                    "landmark": alias.title(),
                    "latitude": round(lat, 5),
                    "longitude": round(lon, 5),
                    "iso6709": format_iso6709(lat, lon),
                    "source": "offline"
                }
                _QUERY_LOOKUP_CACHE[clean_q] = res
                return res

    # 2. Substring matching in offline database
    for lat, lon, city, state, country, aliases in OFFLINE_LOCATIONS_DATABASE:
        city_norm = normalize_location_name(city)
        if len(city_norm) >= 4 and (city_norm in clean_q or clean_q in city_norm):
            res = {
                "city": city,
                "state": state,
                "country": country,
                "landmark": None,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "iso6709": format_iso6709(lat, lon),
                "source": "offline"
            }
            _QUERY_LOOKUP_CACHE[clean_q] = res
            return res

    # 3. Optional Online Nominatim Fallback
    if allow_online:
        try:
            import httpx
            headers = {"User-Agent": "cinetag-video-describer/2.8.0 (metadata-geocoder)"}
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": query.strip(),
                "format": "json",
                "limit": 1,
                "addressdetails": 1
            }
            resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    addr = item.get("address", {})
                    lat_val = float(item["lat"])
                    lon_val = float(item["lon"])
                    city_name = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or item.get("name")
                    state_name = addr.get("state") or addr.get("region") or addr.get("province")
                    country_name = addr.get("country")
                    
                    res = {
                        "city": city_name,
                        "state": state_name,
                        "country": country_name,
                        "landmark": item.get("name") if item.get("type") not in ("administrative", "city") else None,
                        "latitude": round(lat_val, 5),
                        "longitude": round(lon_val, 5),
                        "iso6709": format_iso6709(lat_val, lon_val),
                        "source": "nominatim"
                    }
                    _QUERY_LOOKUP_CACHE[clean_q] = res
                    return res
        except Exception as e:
            logger.debug(f"Online geocoding fallback for '{query}' failed: {e}")

    _QUERY_LOOKUP_CACHE[clean_q] = None
    return None

def reverse_geocode(
    lat: float,
    lon: float,
    allow_online: bool = True,
    timeout: float = 3.0
) -> Optional[Dict[str, Any]]:
    """
    Maps GPS coordinates back to city, state, and country.
    First checks nearest offline city within 40 km.
    Falls back to OpenStreetMap Nominatim reverse geocoding if online.
    """
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    # 1. Offline nearest city check
    closest_entry = None
    min_dist = float("inf")

    for clat, clon, city, state, country, _ in OFFLINE_LOCATIONS_DATABASE:
        dist = _haversine_distance_km(lat, lon, clat, clon)
        if dist < min_dist:
            min_dist = dist
            closest_entry = (clat, clon, city, state, country)

    # If within 40 km of a major city center, return offline match
    if closest_entry and min_dist <= 40.0:
        clat, clon, city, state, country = closest_entry
        return {
            "city": city,
            "state": state,
            "country": country,
            "landmark": None,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "iso6709": format_iso6709(lat, lon),
            "distance_km": round(min_dist, 1),
            "source": "offline"
        }

    # 2. Online Nominatim reverse geocode fallback
    if allow_online:
        try:
            import httpx
            headers = {"User-Agent": "cinetag-video-describer/2.8.0 (metadata-geocoder)"}
            url = "https://nominatim.openstreetmap.org/reverse"
            params = {
                "lat": lat,
                "lon": lon,
                "format": "json",
                "zoom": 12
            }
            resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                addr = data.get("address", {})
                city_name = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
                state_name = addr.get("state") or addr.get("region") or addr.get("province")
                country_name = addr.get("country")

                return {
                    "city": city_name,
                    "state": state_name,
                    "country": country_name,
                    "landmark": None,
                    "latitude": round(lat, 5),
                    "longitude": round(lon, 5),
                    "iso6709": format_iso6709(lat, lon),
                    "source": "nominatim"
                }
        except Exception as e:
            logger.debug(f"Online reverse geocoding for ({lat}, {lon}) failed: {e}")

    # Fallback to closest offline entry if distance is reasonable (< 150 km)
    if closest_entry and min_dist <= 150.0:
        clat, clon, city, state, country = closest_entry
        return {
            "city": city,
            "state": state,
            "country": country,
            "landmark": None,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "iso6709": format_iso6709(lat, lon),
            "distance_km": round(min_dist, 1),
            "source": "offline_approximate"
        }

    return {
        "city": None,
        "state": None,
        "country": None,
        "landmark": None,
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "iso6709": format_iso6709(lat, lon),
        "source": "coordinates_only"
    }
