# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maascli.profile`."""

import pytest

from maascli.profile import (
    get_profile,
    InvalidProfile,
    name_default_profile,
    select_profile,
)
from maascli.testing.config import make_configs
from maastesting.factory import factory


class TestProfile:
    def test_get_profile_finds_profile(self):
        profiles = make_configs()
        [name] = profiles.keys()
        assert profiles[name] == get_profile(profiles, name)

    def test_get_profile_raises_if_not_found(self):
        profiles = make_configs()
        with pytest.raises(InvalidProfile):
            get_profile(profiles, factory.make_name("nonexistent-profile"))

    def test_name_default_profile_picks_single_profile(self):
        profiles = make_configs(1)
        [name] = profiles.keys()
        assert name == name_default_profile(profiles)

    def test_name_default_profile_returns_None_if_no_profile_found(self):
        assert name_default_profile(make_configs(0)) is None

    def test_name_default_profile_returns_None_if_multiple_profiles(self):
        profiles = make_configs(2)
        assert name_default_profile(profiles) is None

    def test_select_profile_returns_named_profile(self):
        profiles = make_configs(3)
        [profile_name, _, _] = profiles
        assert profile_name == select_profile(profiles, profile_name)

    def test_select_profile_selects_default_if_no_profile_named(self):
        profiles = make_configs(1)
        [name] = profiles.keys()
        assert name == select_profile(profiles)
