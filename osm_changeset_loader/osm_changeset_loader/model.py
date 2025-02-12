from datetime import datetime

from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
from shapely.geometry import box
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Metadata(Base):
    __tablename__ = "metadata"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    state = Column(String, nullable=False)


class ChangesetTag(Base):
    __tablename__ = "changeset_tags"

    id = Column(BigInteger, primary_key=True)
    changeset_id = Column(BigInteger, ForeignKey("changesets.id"), index=True)
    k = Column(String, nullable=False)
    v = Column(String)

    changeset = relationship("Changeset", back_populates="tags")


class ChangesetComment(Base):
    __tablename__ = "changeset_comments"

    id = Column(BigInteger, primary_key=True)
    changeset_id = Column(BigInteger, ForeignKey("changesets.id"), index=True)
    uid = Column(BigInteger)
    user = Column(String)
    date = Column(DateTime)
    text = Column(String)

    changeset = relationship("Changeset", back_populates="comments")


class Changeset(Base):
    __tablename__ = "changesets"

    __table_args__ = (
        Index("idx_changesets_user", "user"),
        Index("idx_changesets_created_at", "created_at"),
        Index("idx_changesets_bbox", "min_lon", "max_lon", "min_lat", "max_lat"),
        Index("idx_changesets_user_created_at", "user", "created_at"),
        Index("idx_changesets_num_changes", "num_changes"),
        Index("idx_changesets_comments_count", "comments_count"),
        Index("idx_changesets_bbox_geom", "bbox", postgresql_using="gist"),
    )

    id = Column(BigInteger, primary_key=True)
    user = Column(String)
    uid = Column(BigInteger)
    created_at = Column(DateTime)
    closed_at = Column(DateTime)
    open = Column(Boolean)
    num_changes = Column(Integer)
    comments_count = Column(Integer)
    min_lat = Column(Float)
    min_lon = Column(Float)
    max_lat = Column(Float)
    max_lon = Column(Float)
    bbox = Column(Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True))

    tags = relationship(
        "ChangesetTag", back_populates="changeset", cascade="all, delete-orphan"
    )
    comments = relationship(
        "ChangesetComment", back_populates="changeset", cascade="all, delete-orphan"
    )

    @classmethod
    def from_xml(cls, elem):
        """
        Create a Changeset instance from an XML element.
        """
        changeset = cls()
        # Ensure we have a valid ID
        try:
            changeset.id = int(elem.attrib.get("id", "0"))
            if changeset.id <= 0:
                return None
        except ValueError:
            return None

        changeset.user = elem.attrib.get("user", None)
        changeset.uid = int(elem.attrib.get("uid", 0))
        changeset.created_at = (
            datetime.fromisoformat(elem.attrib.get("created_at"))
            if elem.attrib.get("created_at")
            else None
        )
        changeset.closed_at = (
            datetime.fromisoformat(elem.attrib.get("closed_at"))
            if elem.attrib.get("closed_at")
            else None
        )
        changeset.open = elem.attrib.get("open", None) == "true"
        changeset.num_changes = int(elem.attrib.get("num_changes", 0))
        changeset.comments_count = int(elem.attrib.get("comments_count", 0))
        changeset.min_lat = float(elem.attrib.get("min_lat", 0))
        changeset.min_lon = float(elem.attrib.get("min_lon", 0))
        changeset.max_lat = float(elem.attrib.get("max_lat", 0))
        changeset.max_lon = float(elem.attrib.get("max_lon", 0))

        # Set the new bbox field using shapely and geoalchemy2.
        # Create a box using (min_lon, min_lat, max_lon, max_lat)
        changeset.bbox = from_shape(
            box(
                changeset.min_lon,
                changeset.min_lat,
                changeset.max_lon,
                changeset.max_lat,
            ),
            srid=4326,
        )

        # Parse tags
        changeset.tags = [
            ChangesetTag(k=tag.attrib["k"], v=tag.attrib["v"])
            for tag in elem.findall("tag")
        ]

        # Parse discussion comments
        discussion = elem.find("discussion")
        changeset.comments = []
        if discussion is not None:
            changeset.comments = [
                ChangesetComment(
                    uid=int(comment.attrib["uid"]),
                    user=comment.attrib["user"],
                    date=datetime.fromisoformat(comment.attrib["date"]),
                    text=(
                        comment.find("text").text
                        if comment.find("text") is not None
                        else None
                    ),
                )
                for comment in discussion.findall("comment")
            ]

        return changeset
