"""Domain-specific exceptions for VRE operations"""


class VREError(Exception):
    """Base exception for all VRE-related errors"""

    pass


class VREConfigurationError(VREError):
    """Raised when the crate does not contain enough information to resolve a service."""

    pass


class WorkflowConfigurationError(VREError):
    """Raised when workflow configuration is invalid"""

    pass


class WorkflowURLError(WorkflowConfigurationError):
    """Raised when workflow URL is missing or malformed"""

    pass


class FileProcessingError(VREError):
    """Raised when file processing fails"""

    pass


class ExternalServiceError(VREError):
    """Raised when external service (Galaxy, Binder, etc.) fails"""

    pass


class GalaxyAPIError(ExternalServiceError):
    """Raised when Galaxy API communication fails"""

    pass


class InvalidGalaxyResponseError(ExternalServiceError):
    """Raised when Galaxy API returns unexpected response"""

    pass


class InvalidResponseError(ExternalServiceError):
    """Raised when external service returns unexpected response"""

    pass


class ExternalDataSourceError(VREError):
    """Raised when external source fails"""

    pass
