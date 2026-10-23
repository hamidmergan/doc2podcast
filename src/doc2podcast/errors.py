class PodcastError(Exception):
    """Base class of all errors in this package."""


class ConfigError(PodcastError):
    """A setting is missing or a value is invalid."""


class LimitError(PodcastError):
    """A limit was exceeded."""


class EmptyTextError(PodcastError):
    """There is no material to work with."""


class UnsupportedFileError(PodcastError):
    """The file type is not supported or the file cannot be read."""


class ModelError(PodcastError):
    """The server did not answer, or the answer was unusable."""


class ScriptUnusable(ModelError):
    """The answer was not a usable script, the caller may try once more."""


class ScriptFormatError(PodcastError):
    """A script file cannot be read. The person who wrote it has to change it."""


class AudioError(PodcastError):
    """ffmpeg is missing or could not join the audio parts."""
