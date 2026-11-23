# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for enum-related utilities."""

from provisioningserver.utils.enum import map_enum, map_enum_reverse


class TestEnum:
    def test_map_enum_includes_all_enum_keys(self):
        class Enum:
            ONE = 1
            TWO = 2

        assert {"ONE", "TWO"} == map_enum(Enum).keys()

    def test_map_enum_omits_private_or_special_methods(self):
        class Enum:
            def __init__(self):
                pass

            def __repr__(self):
                return "Enum"

            def _save(self):
                pass

            VALUE = 9

        assert {"VALUE"} == map_enum(Enum).keys()

    def test_map_enum_maps_values(self):
        class Enum:
            ONE = 1
            THREE = 3

        assert {"ONE": 1, "THREE": 3} == map_enum(Enum)

    def test_map_enum_reverse_maps_values(self):
        class Enum:
            ONE = 1
            NINE = 9

        assert {1: "ONE", 9: "NINE"} == map_enum_reverse(Enum)

    def test_map_enum_reverse_ignores_unwanted_keys(self):
        class Enum:
            ZERO = 0
            ONE = 1

        assert {0: "ZERO"} == map_enum_reverse(Enum, ignore=["ONE"])

    def test_map_enum_reverse_ignores_keys_for_clashing_values(self):
        class Enum:
            ONE = 1
            FIVE = 5
            ONE_2 = 1
            TWO = 2
            THREE_2 = 3
            THREE = 3
            FOUR_2 = 4
            TWO_2 = 2
            FOUR = 4
            FIVE_2 = 5

        assert {
            1: "ONE",
            2: "TWO",
            3: "THREE",
            4: "FOUR",
            5: "FIVE",
        } == map_enum_reverse(
            Enum, ignore=["ONE_2", "TWO_2", "THREE_2", "FOUR_2", "FIVE_2"]
        )
