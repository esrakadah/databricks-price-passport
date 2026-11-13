"""The versioned tariff rule that turns a wholesale forecast into a price (decisions section 10).

A rule never changes once a price was scored with it: a new parameter is a new version, and every version that ever
priced a row stays here, so the lineage check can find the rule a stored price names. The hash covers the parameters,
and a test pins it, so a parameter changed without a new version fails CI.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

EUR_MWH_PER_CT_KWH = 10
HASH_LENGTH = 16


@dataclass(frozen=True)
class TariffRule:
    version: int
    supplier_margin_ct_kwh: float
    vat_rate: float

    def price_ct_kwh(self, forecast_eur_mwh: float) -> float:
        """Energy price per kWh including VAT. Negative forecasts pass through as negative prices, as in dynamic
        tariffs; grid fees, levies and the standing charge are outside this demonstration."""
        return round((forecast_eur_mwh / EUR_MWH_PER_CT_KWH + self.supplier_margin_ct_kwh) * (1 + self.vat_rate), 4)

    @property
    def parameter_hash(self) -> str:
        parameters = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(parameters.encode("utf-8")).hexdigest()[:HASH_LENGTH]


RULES = {rule.version: rule for rule in (TariffRule(version=1, supplier_margin_ct_kwh=2.0, vat_rate=0.19),)}
CURRENT_RULE = RULES[max(RULES)]
