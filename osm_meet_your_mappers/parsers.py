import logging
from functools import lru_cache
from typing import Optional
from datetime import datetime
from lxml import etree
from shapely import Point, box


@lru_cache(maxsize=128)
def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception as ex:
        logging.warning(f"Failed to parse datetime '{dt_str}': {ex}")
        return None


def parse_changeset(elem: etree._Element) -> Optional[dict]:
    """Parse a changeset element into a dictionary."""
    cs_id = int(elem.attrib.get("id", "0"))
    if cs_id <= 0:
        return None

    min_lon = float(elem.attrib.get("min_lon", 0))
    min_lat = float(elem.attrib.get("min_lat", 0))
    max_lon = float(elem.attrib.get("max_lon", 0))
    max_lat = float(elem.attrib.get("max_lat", 0))

    geometry = (
        Point(min_lon, min_lat)
        if abs(min_lon - max_lon) < 1e-7 and abs(min_lat - max_lat) < 1e-7
        else box(min_lon, min_lat, max_lon, max_lat)
    )

    tags = {tag.attrib["k"]: tag.attrib.get("v") for tag in elem.findall("tag")}

    comments = [
        {
            "uid": int(comment.attrib.get("uid", 0)),
            "username": comment.attrib.get("username"),
            "date": (
                parse_datetime(comment.attrib.get("date")).isoformat()
                if comment.attrib.get("date")
                else None
            ),
            "text": comment.findtext("text"),
        }
        for comment in elem.findall("discussion/comment")
    ]

    return {
        "id": cs_id,
        "username": elem.attrib.get("user"),
        "uid": int(elem.attrib.get("uid", 0)),
        "created_at": parse_datetime(elem.attrib.get("created_at")),
        "closed_at": parse_datetime(elem.attrib.get("closed_at")),
        "open": elem.attrib.get("open", "false").lower() == "true",
        "num_changes": int(elem.attrib.get("num_changes", 0)),
        "comments_count": len(comments),
        "tags": tags,
        "comments": comments,
        "bbox": geometry.wkt,
    }
