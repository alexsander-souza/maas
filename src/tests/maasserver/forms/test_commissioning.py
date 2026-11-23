# Copyright 2014-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for commissioning forms."""

import pytest

from maasserver.enum import BOOT_RESOURCE_TYPE
from maasserver.forms import CommissioningForm
from maasserver.models import Config
from maasserver.models.signals.testing import SignalsDisabled
from maasserver.testing.factory import factory
from maasserver.utils.forms import compose_invalid_choice_text


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCommissioningFormForm:
    @pytest.fixture
    def disable_bootsources_signals(self):
        with SignalsDisabled("bootsources"):
            yield

    def test_commissioningform_error_msg_lists_series_choices(self):
        form = CommissioningForm()
        field = form.fields["commissioning_distro_series"]
        assert field.error_messages[
            "invalid_choice"
        ] == compose_invalid_choice_text(
            "commissioning_distro_series", field.choices
        )

    def test_commissioningform_error_msg_lists_min_hwe_kernel_choices(self):
        form = CommissioningForm()
        field = form.fields["default_min_hwe_kernel"]
        assert field.error_messages[
            "invalid_choice"
        ] == compose_invalid_choice_text(
            "default_min_hwe_kernel", field.choices
        )

    def test_commissioningform_contains_real_and_ui_choice(
        self, disable_bootsources_signals
    ):
        release = factory.pick_ubuntu_release()
        series = release.series
        name = "ubuntu/%s" % series
        arch = factory.make_name("arch")
        kernel = "hwe-" + release.version.split(" ")[0]
        # Disable boot sources signals otherwise the test fails due to unrun
        # post-commit tasks at the end of the test.
        factory.make_RegionController()
        factory.make_BootSourceCache(os=name, subarch=kernel, release=series)
        factory.make_usable_boot_resource(
            name=name,
            architecture=f"{arch}/{kernel}",
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
        )
        Config.objects.set_config("commissioning_distro_series", series)
        form = CommissioningForm()
        assert sorted(
            [
                ("", "--- No minimum kernel ---"),
                (kernel, f"{series} ({kernel})"),
            ]
        ) == sorted(form.fields["default_min_hwe_kernel"].choices)
