class ParseError(Exception):
    """Raised when a parser encounters bad data in a file."""

    def __init__(self, file: str, row: int | None, message: str):
        self.file = file
        self.row = row
        self.message = message
        if row is not None:
            super().__init__(f"{file} row {row}: {message}")
        else:
            super().__init__(f"{file}: {message}")
