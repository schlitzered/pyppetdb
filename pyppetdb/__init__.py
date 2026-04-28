import warnings
try:
    from authlib.deprecate import AuthlibDeprecationWarning
    # TODO: Remove this warning suppression once Authlib is updated to a version
    # that fixes internal deprecated imports (Issue #880).
    # Suppress Authlib deprecation warning regarding jose/joserfc transition
    warnings.filterwarnings("ignore", category=AuthlibDeprecationWarning)
except ImportError:
    pass
