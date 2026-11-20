"""Landmark list for probing and viewer markers. --geocode refreshes coordinates from Nominatim
(1 request/s, generic user agent) and records which source each coordinate came from."""
import argparse
import json
import time
import urllib.parse
import urllib.request

from geo import ROOT

PLACES = [
    # name, nominatim query, fallback lat, lon, level, blurb
    ("Temple Square", "Temple Square, Salt Lake City", 40.7704, -111.8920, "detail", "Ten-acre block around the Salt Lake Temple; the camera anchor."),
    ("Utah State Capitol", "Utah State Capitol, Salt Lake City", 40.7774, -111.8882, "detail", "Capitol Hill, above downtown to the north."),
    ("City Creek Center", "City Creek Center, Salt Lake City", 40.7685, -111.8925, "detail", "Downtown shopping district with the creek running through it."),
    ("Delta Center", "Delta Center, Salt Lake City", 40.7683, -111.9011, "detail", "Arena on the west side of downtown."),
    ("Salt Palace Convention Center", "Salt Palace Convention Center", 40.7665, -111.8960, "detail", "Convention centre on West Temple."),
    ("Salt Lake City Public Library", "Salt Lake City Main Library", 40.7608, -111.8846, "detail", "Main library on Library Square."),
    ("City and County Building", "Salt Lake City and County Building", 40.7598, -111.8863, "detail", "City hall on Washington Square."),
    ("The Gateway", "The Gateway, Salt Lake City", 40.7666, -111.9035, "detail", "Mixed-use district by the old Union Pacific depot."),
    ("Rio Grande Depot", "Rio Grande Depot, Salt Lake City", 40.7612, -111.9045, "detail", "1910 railway depot."),
    ("University of Utah", "Park Building, University of Utah", 40.7636, -111.8530, "detail", "Presidents Circle on the east bench."),
    ("Rice-Eccles Stadium", "Rice-Eccles Stadium", 40.7600, -111.8489, "detail", "University stadium; 2002 Olympic ceremonies."),
    ("Liberty Park", "Liberty Park, Salt Lake City", 40.7456, -111.8744, "detail", "The city's large central park, with Tracy Aviary."),
    ("Trolley Square", "Trolley Square, Salt Lake City", 40.7563, -111.8721, "detail", "Former trolley barns turned shopping centre."),
    ("Ensign Peak", "Ensign Peak, Salt Lake City", 40.7924, -111.8939, "detail", "Foothill summit north of the Capitol."),
    ("Memory Grove Park", "Memory Grove Park, Salt Lake City", 40.7756, -111.8857, "detail", "Park in lower City Creek Canyon."),
    ("Salt Lake City International Airport", "Salt Lake City International Airport", 40.7884, -111.9778, "overview", "Airport on the flats west of the city."),
    ("Great Salt Lake (Saltair)", "Saltair, Utah", 40.7651, -112.1785, "overview", "South shore of the Great Salt Lake."),
]


def geocode(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "tiny-city-pipeline/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    return (float(res[0]["lat"]), float(res[0]["lon"])) if res else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geocode", action="store_true")
    a = ap.parse_args()
    out = []
    for name, q, lat, lon, level, blurb in PLACES:
        src = "fallback"
        if a.geocode:
            got = geocode(q)
            time.sleep(1.1)
            if got and abs(got[0] - lat) < 0.02 and abs(got[1] - lon) < 0.02:
                lat, lon, src = round(got[0], 6), round(got[1], 6), "nominatim"
            elif got:
                print(f"{name}: nominatim answer {got} too far from fallback; keeping fallback")
        out.append({"name": name, "lat": lat, "lon": lon, "level": level, "blurb": blurb, "source": src})
        print(f"{name:38s} {lat:.5f} {lon:.5f} {src}")
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "places.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
