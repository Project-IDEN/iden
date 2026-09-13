import pytest

from provider.authz.services.auth_methods import (
    derive_acr,
    meets,
    normalized_amr,
    outstanding,
    reachable_levels,
    supported,
)
from provider.shared.enums import AcrLevel


@pytest.mark.parametrize(
    "amr,expected",
    [
        (["pwd"], AcrLevel.LOA1),
        (["face"], AcrLevel.LOA1),
        (["pwd", "otp"], AcrLevel.LOA2),
        (["pwd", "face"], AcrLevel.LOA3),
        (["face", "otp"], AcrLevel.LOA3),
        (["pwd", "otp", "face"], AcrLevel.LOA3),
    ],
)
def test_acr_is_derived_from_the_methods_used(amr, expected):
    assert derive_acr(amr) == expected


def test_repeated_method_is_still_one_factor():
    assert derive_acr(["pwd", "pwd"]) == AcrLevel.LOA1


def test_mfa_is_added_for_two_or_more_factors():
    assert normalized_amr(["pwd", "otp"]) == ["pwd", "otp", "mfa"]


def test_mfa_is_absent_for_a_single_factor():
    assert normalized_amr(["pwd"]) == ["pwd"]


def test_mfa_is_not_counted_as_a_factor_itself():
    assert derive_acr(["pwd", "mfa"]) == AcrLevel.LOA1


@pytest.mark.parametrize(
    "amr,required,expected",
    [
        (["pwd"], None, True),
        (["pwd"], "iden:loa:1", True),
        (["pwd"], "iden:loa:2", False),
        (["pwd", "otp"], "iden:loa:2", True),
        (["pwd", "face"], "iden:loa:2", True),
        (["pwd", "otp"], "iden:loa:3", False),
        (["pwd"], "nonsense", True),
    ],
)
def test_meets_compares_levels_in_order(amr, required, expected):
    """A higher level satisfies a request for a lower one."""
    assert meets(derive_acr(amr), required) is expected


def test_face_is_not_registered_until_the_biometric_module_is_enabled():
    assert supported() == ["pwd", "otp"]


def test_only_reachable_levels_are_advertised():
    assert reachable_levels() == ["iden:loa:1", "iden:loa:2"]


@pytest.mark.parametrize(
    "amr,enrolled,required,expected",
    [
        # Nothing asked, nothing owed.
        (["pwd"], {"pwd"}, None, []),
        # The person's own rule: an authenticator, once set up, is always owed.
        (["pwd"], {"pwd", "otp"}, None, ["otp"]),
        (["pwd", "otp"], {"pwd", "otp"}, None, []),
        # The client's rule, when the person can meet it.
        (["pwd"], {"pwd", "otp"}, "iden:loa:2", ["otp"]),
        # ...and when they cannot: nothing to ask for, so /authorize refuses.
        (["pwd"], {"pwd"}, "iden:loa:2", []),
        (["pwd", "otp"], {"pwd", "otp"}, "iden:loa:3", []),
    ],
)
def test_outstanding_asks_only_for_what_can_help(amr, enrolled, required, expected):
    assert outstanding(amr, enrolled, required) == expected
