import bz2
import csv
import xml.etree.ElementTree as ET

OSM_CHANGESET_FILE = "/Users/mvexel/data/osm/changesets-250127.osm.bz2"
CSV_OUTPUT_FILE = "/Users/mvexel/data/osm/changesets.csv"


def parse_changesets_to_csv(file_path, csv_output_path):
    """
    Parse changeset XML and write to CSV.
    """
    with bz2.open(file_path, "rb") as f, open(
        csv_output_path, "w", newline=""
    ) as csvfile:
        writer = csv.writer(csvfile)
        # Write CSV header
        writer.writerow(
            [
                "id",
                "user",
                "uid",
                "created_at",
                "closed_at",
                "open",
                "min_lat",
                "min_lon",
                "max_lat",
                "max_lon",
                "bbox_area_km2",
                "centroid_lon",
                "centroid_lat",
            ]
        )

        context = ET.iterparse(f, events=("start", "end"))
        _, root = next(context)  # get the root element

        for event, elem in context:
            if event == "start" and elem.tag == "changeset":
                # Extract attributes
                changeset = {
                    "id": elem.attrib.get("id", 0),
                    "user": elem.attrib.get("user", None),
                    "uid": elem.attrib.get("uid", 0),
                    "created_at": elem.attrib.get("created_at", None),
                    "closed_at": elem.attrib.get("closed_at", None),
                    "open": elem.attrib.get("open", None) == "true",
                    "min_lat": float(elem.attrib.get("min_lat", 0)),
                    "min_lon": float(elem.attrib.get("min_lon", 0)),
                    "max_lat": float(elem.attrib.get("max_lat", 0)),
                    "max_lon": float(elem.attrib.get("max_lon", 0)),
                }

                # Calculate centroid and bbox area
                changeset["centroid_lon"] = (
                    changeset["min_lon"] + changeset["max_lon"]
                ) / 2
                changeset["centroid_lat"] = (
                    changeset["min_lat"] + changeset["max_lat"]
                ) / 2
                changeset["bbox_area_km2"] = (
                    (changeset["max_lat"] - changeset["min_lat"])
                    * (changeset["max_lon"] - changeset["min_lon"])
                    * 111.32**2
                )

                # Write row to CSV
                writer.writerow(
                    [
                        changeset["id"],
                        changeset["user"],
                        changeset["uid"],
                        changeset["created_at"],
                        changeset["closed_at"],
                        changeset["open"],
                        changeset["min_lat"],
                        changeset["min_lon"],
                        changeset["max_lat"],
                        changeset["max_lon"],
                        changeset["bbox_area_km2"],
                        changeset["centroid_lon"],
                        changeset["centroid_lat"],
                    ]
                )

                root.clear()  # clear the root element to save memory


if __name__ == "__main__":
    parse_changesets_to_csv(OSM_CHANGESET_FILE, CSV_OUTPUT_FILE)
