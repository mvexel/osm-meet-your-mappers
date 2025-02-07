class Path:
    def __init__(self, sequence=None, path_tuple=None):
        if sequence is not None:
            self.sequence = sequence
            self.path_tuple = self._sequence_to_path(sequence)
        elif path_tuple is not None:
            self.path_tuple = path_tuple
            self.sequence = self._path_to_sequence(path_tuple)
        else:
            raise ValueError("Either sequence or path_tuple must be provided")

    def _sequence_to_path(self, sequence):
        """
        Convert a sequence integer to a path tuple.
        """
        sequence_str = str(sequence).zfill(9)
        return (sequence_str[:3], sequence_str[3:6], sequence_str[6:9])

    def _path_to_sequence(self, path_tuple):
        """
        Convert a path tuple to a sequence integer.
        """
        return int("".join(path_tuple))

    def to_url(self):
        """
        Convert the path to a URL.
        """
        return f"https://planet.osm.org/replication/changesets/{'/'.join(self.path_tuple)}.osm.gz"

    def __eq__(self, other):
        if isinstance(other, Path):
            return self.sequence == other.sequence
        return False

    def __lt__(self, other):
        if isinstance(other, Path):
            return self.sequence < other.sequence
        return False

    def __le__(self, other):
        if isinstance(other, Path):
            return self.sequence <= other.sequence
        return False

    def __gt__(self, other):
        if isinstance(other, Path):
            return self.sequence > other.sequence
        return False

    def __ge__(self, other):
        if isinstance(other, Path):
            return self.sequence >= other.sequence
        return False

    def __repr__(self):
        return f"Path(sequence={self.sequence}, path_tuple={self.path_tuple})"
