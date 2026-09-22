class MosaicHarnessError(Exception):
    """Base exception for Mosaic Harness."""


class InvalidAgentSpecError(MosaicHarnessError, ValueError):
    """Invalid public AgentSpec."""


class DuplicateAgentError(MosaicHarnessError):
    """Agent name already exists."""


class UnknownAgentError(MosaicHarnessError, LookupError):
    """Agent name does not exist."""


class DuplicateToolError(MosaicHarnessError):
    """Tool name already exists."""


class UnknownToolError(MosaicHarnessError, LookupError):
    """Tool name does not exist."""


class MissingOptionalDependencyError(MosaicHarnessError, ImportError):
    """Optional integration is not installed."""


class UnknownModelProviderError(MosaicHarnessError, ValueError):
    """Model provider is not registered."""


class NoCompatibleModelError(MosaicHarnessError, ValueError):
    """No candidate model satisfies the requested capabilities."""


class InvalidModelSpecError(MosaicHarnessError, ValueError):
    """Invalid declarative model configuration."""


class UnsupportedModelCapabilityError(MosaicHarnessError, ValueError):
    """The selected model explicitly does not support a required capability."""


class InvalidMCPConfigError(MosaicHarnessError, ValueError):
    """Invalid MCP configuration."""
