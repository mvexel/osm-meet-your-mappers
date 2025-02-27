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
    try:
        # Validate required fields
        cs_id = int(elem.attrib.get("id", "0"))
        if cs_id <= 0:
            logging.warning(f"Invalid changeset ID: {cs_id}")
            return None

        # Validate coordinates
        try:
            min_lon = float(elem.attrib.get("min_lon", 0))
            min_lat = float(elem.attrib.get("min_lat", 0))
            max_lon = float(elem.attrib.get("max_lon", 0))
            max_lat = float(elem.attrib.get("max_lat", 0))

            # Validate coordinate ranges
            if (
                not (-180 <= min_lon <= 180)
                or not (-180 <= max_lon <= 180)
                or not (-90 <= min_lat <= 90)
                or not (-90 <= max_lat <= 90)
            ):
                logging.warning(f"Invalid coordinates in changeset {cs_id}")
                return None

            geometry = (
                Point(min_lon, min_lat)
                if abs(min_lon - max_lon) < 1e-7 and abs(min_lat - max_lat) < 1e-7
                else box(min_lon, min_lat, max_lon, max_lat)
            )
        except (ValueError, TypeError) as e:
            logging.warning(f"Invalid geometry in changeset {cs_id}: {e}")
            return None

        # Parse tags
        tags = {}
        for tag in elem.findall("tag"):
            try:
                k = tag.attrib.get("k")
                v = tag.attrib.get("v")
                if k and v:  # Only include non-empty tags
                    tags[k] = v
            except Exception as e:
                logging.warning(f"Error parsing tag in changeset {cs_id}: {e}")

        # Parse comments
        comments = []
        for comment in elem.findall("discussion/comment"):
            try:
                comment_data = {
                    "uid": int(comment.attrib.get("uid", 0)),
                    "username": comment.attrib.get("username") or "",
                    "date": (
                        parse_datetime(comment.attrib.get("date")).isoformat()
                        if comment.attrib.get("date")
                        else None
                    ),
                    "text": comment.findtext("text") or "",
                }
                comments.append(comment_data)
            except Exception as e:
                logging.warning(f"Error parsing comment in changeset {cs_id}: {e}")

        # Username can be null for anonymous edits
        username = elem.attrib.get("user")

        # Validate timestamps
        created_at = parse_datetime(elem.attrib.get("created_at"))
        closed_at = parse_datetime(elem.attrib.get("closed_at"))
        if not closed_at:
            return None

        return {
            "id": cs_id,
            "username": username,
            "uid": int(elem.attrib.get("uid", 0)),
            "created_at": created_at,
            "closed_at": closed_at,
            "open": elem.attrib.get("open", "false").lower() == "true",
            "num_changes": int(elem.attrib.get("num_changes", 0)),
            "comments_count": len(comments),
            "tags": tags,
            "comments": comments,
            "bbox": geometry.wkt,
        }
    except Exception as e:
        logging.error(f"Error parsing changeset: {e}", exc_info=True)
        return None
