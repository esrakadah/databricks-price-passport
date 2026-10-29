"""Price Passport: hourly energy prices from a versioned model, traceable back to the data that trained it."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("price-passport")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
