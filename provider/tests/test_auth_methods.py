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
        (["pwd"], AcrLevel.SFA),
        (["face"], AcrLevel.SFA),
        (["pwd", "otp"], AcrLevel.MFA),
        (["pwd", "face"], AcrLevel.MFA_FACE),
        (["face", "otp"], AcrLevel.MFA_FACE),
        (["pwd", "otp", "face"], AcrLevel.MFA_FACE),
    ],
)
def test_acr_is_derived_from_the_methods_used(amr, expected):
    assert derive_acr(amr) == expected


def test_repeated_method_is_still_one_factor():
    assert derive_acr(["pwd", "pwd"]) == AcrLevel.SFA


def test_mfa_is_added_for_two_or_more_factors():
    assert normalized_amr(["pwd", "otp"]) == ["pwd", "otp", "mfa"]


def test_mfa_is_absent_for_a_single_factor():
    assert normalized_amr(["pwd"]) == ["pwd"]


def test_mfa_is_not_counted_as_a_factor_itself():
    assert derive_acr(["pwd", "mfa"]) == AcrLevel.SFA


@pytest.mark.parametrize(
    "amr,required,expected",
    [
        (["pwd"], None, True),
        (["pwd"], "urn:iden:acr:sfa", True),
        (["pwd"], "urn:iden:acr:mfa", False),
        (["pwd", "otp"], "urn:iden:acr:mfa", True),
        (["pwd", "face"], "urn:iden:acr:mfa", True),
        (["pwd", "otp"], "urn:iden:acr:mfa-face", False),
        (["pwd"], "nonsense", True),
    ],
)
def test_meets_compares_levels_in_order(amr, required, expected):
    """A higher level satisfies a request for a lower one."""
    assert meets(derive_acr(amr), required) is expected


def test_face_is_not_registered_until_the_biometric_module_is_enabled():
    assert supported() == ["pwd", "otp"]


def test_only_reachable_levels_are_advertised():
    assert reachable_levels() == ["urn:iden:acr:sfa", "urn:iden:acr:mfa"]


@pytest.mark.parametrize(
    "amr,enrolled,required,expected",
    [
        # Nothing asked, nothing owed.
        (["pwd"], {"pwd"}, None, []),
        # The person's own rule: an authenticator, once set up, is always owed.
        (["pwd"], {"pwd", "otp"}, None, ["otp"]),
        (["pwd", "otp"], {"pwd", "otp"}, None, []),
        # The client's rule, when the person can meet it.
        (["pwd"], {"pwd", "otp"}, "urn:iden:acr:mfa", ["otp"]),
        # ...and when they cannot: nothing to ask for, so /authorize refuses.
        (["pwd"], {"pwd"}, "urn:iden:acr:mfa", []),
        (["pwd", "otp"], {"pwd", "otp"}, "urn:iden:acr:mfa-face", []),
    ],
)
def test_outstanding_asks_only_for_what_can_help(amr, enrolled, required, expected):
    assert outstanding(amr, enrolled, required) == expected
