from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Metadata(Base):
    __tablename__ = "metadata"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    state = Column(String, nullable=False)


class Changeset(Base):
    __tablename__ = "changesets"

    id = Column(Integer, primary_key=True)
    user = Column(String)
    uid = Column(Integer)
    created_at = Column(DateTime)
    closed_at = Column(DateTime)
    open = Column(Boolean)
    min_lat = Column(Float)
    min_lon = Column(Float)
    max_lat = Column(Float)
    max_lon = Column(Float)
    bbox_area_km2 = Column(Float)
    centroid_lon = Column(Float)
    centroid_lat = Column(Float)

    @classmethod
    def from_xml(cls, elem):
        """
        Create a Changeset instance from an XML element.
        """
        changeset = cls()
        changeset.id = int(elem.attrib.get("id", 0))
        changeset.user = elem.attrib.get("user", None)
        changeset.uid = int(elem.attrib.get("uid", 0))
        changeset.created_at = elem.attrib.get("created_at", None)
        changeset.closed_at = elem.attrib.get("closed_at", None)
        changeset.open = elem.attrib.get("open", None) == "true"
        changeset.min_lat = float(elem.attrib.get("min_lat", 0))
        changeset.min_lon = float(elem.attrib.get("min_lon", 0))
        changeset.max_lat = float(elem.attrib.get("max_lat", 0))
        changeset.max_lon = float(elem.attrib.get("max_lon", 0))

        # Calculate centroid and bbox area
        changeset.centroid_lon = (changeset.min_lon + changeset.max_lon) / 2
        changeset.centroid_lat = (changeset.min_lat + changeset.max_lat) / 2

        # Calculate bbox area in km2
        bbox_area_km2 = (
            (changeset.max_lat - changeset.min_lat)
            * (changeset.max_lon - changeset.min_lon)
            * 111.32**2
        )
        changeset.bbox_area_km2 = bbox_area_km2

        return changeset
