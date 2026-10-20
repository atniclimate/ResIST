"""Typed errors with D-060 exit codes. Imports nothing from resist, so models can import it.

Messages carry reason codes, names and SHA-256 values only, never document text.
"""

EXIT_OK, EXIT_BAD_INPUT, EXIT_DEPENDENCY, EXIT_SOME_FAILED, EXIT_ARTIFACT = 0, 1, 2, 3, 4  # D-060


class ResistError(Exception):
    exit_code = EXIT_BAD_INPUT


class BadInput(ResistError):
    exit_code = EXIT_BAD_INPUT


class TierRefused(BadInput):
    """Raised before a byte of the document is opened (U8)."""


class QuarantinedError(TierRefused):
    """NCAI / DG-12 material (D-040)."""


class ModelProvenanceError(BadInput):
    """U9: a model-interpretation marker in provenance."""


class InvalidConfig(ResistError):
    exit_code = EXIT_DEPENDENCY


class DependencyError(ResistError):
    """CLI exit 2; HTTP 503 later."""

    exit_code = EXIT_DEPENDENCY

    def __init__(self, reason: str, remediation: str = ""):
        super().__init__(reason if not remediation else f"{reason} ({remediation})")
        self.reason = reason
        self.remediation = remediation


class ArtifactError(ResistError):
    exit_code = EXIT_ARTIFACT
