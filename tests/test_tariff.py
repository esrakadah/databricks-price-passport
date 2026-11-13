import pytest

from price_passport.tariff import CURRENT_RULE, RULES, TariffRule

PINNED_HASHES = {1: "a4c32fe853a68bcc"}


def test_every_rule_keeps_its_pinned_hash():
    """A parameter changed without a new version would reprice rows that already name the old rule."""
    assert {version: rule.parameter_hash for version, rule in RULES.items()} == PINNED_HASHES


def test_the_current_rule_is_the_newest():
    assert CURRENT_RULE.version == max(RULES)


def test_rule_one_adds_the_margin_and_vat_to_the_forecast_in_cent_per_kwh():
    assert RULES[1].price_ct_kwh(100.0) == pytest.approx((10.0 + 2.0) * 1.19)


def test_a_negative_forecast_passes_through():
    assert RULES[1].price_ct_kwh(-50.0) == pytest.approx((-5.0 + 2.0) * 1.19)


def test_the_hash_follows_every_parameter():
    base = TariffRule(version=1, supplier_margin_ct_kwh=2.0, vat_rate=0.19)

    assert TariffRule(version=1, supplier_margin_ct_kwh=2.5, vat_rate=0.19).parameter_hash != base.parameter_hash
    assert TariffRule(version=1, supplier_margin_ct_kwh=2.0, vat_rate=0.07).parameter_hash != base.parameter_hash
