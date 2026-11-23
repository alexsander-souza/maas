# Copyright 2016-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for DHCP snippets forms."""

import random

from django.core.exceptions import ValidationError
from django.http import HttpRequest
import pytest

from maascommon.events import AUDIT
from maasserver.enum import ENDPOINT_CHOICES
from maasserver.forms.packagerepository import PackageRepositoryForm
from maasserver.models import Event, PackageRepository
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from maastesting.gpg import SAMPLE_GPG_PUBLIC_KEY


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPackageRepositoryForm:
    def make_valid_repo_params(self, repo=None):
        # Helper that creates a valid PackageRepository and parameters for a
        # PackageRepositoryForm that will validate.
        if repo is None:
            repo = factory.make_PackageRepository()
        name = factory.make_name("name")
        url = factory.make_url(scheme="http")
        arch1 = random.choice(PackageRepository.KNOWN_ARCHES)
        arch2 = random.choice(PackageRepository.KNOWN_ARCHES)
        dist1 = factory.make_name("dist")
        dist2 = factory.make_name("dist")
        pock1 = "updates"
        pock2 = "backports"
        comp1 = "universe"
        comp2 = "multiverse"
        disable_sources = factory.pick_bool()
        enabled = factory.pick_bool()
        params = {
            "name": name,
            "url": url,
            "distributions": [dist1, dist2],
            "disabled_pockets": [pock1, pock2],
            "components": [comp1, comp2],
            "arches": [arch1, arch2],
            "enabled": enabled,
            "disable_sources": disable_sources,
        }
        return params

    def test_creates_package_repository(self):
        repo = factory.make_PackageRepository()
        params = self.make_valid_repo_params(repo)
        form = PackageRepositoryForm(data=params)
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        for key, value in params.items():
            assert getattr(package_repository, key) == value
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == (
            "Created package repository '%s'." % package_repository.name
        )

    def test_create_package_repository_requires_name(self):
        form = PackageRepositoryForm(
            data={"url": factory.make_url(scheme="http")}
        )
        assert not form.is_valid()

    def test_create_package_repository_requires_url(self):
        form = PackageRepositoryForm(data={"name": factory.make_name("name")})
        assert not form.is_valid()

    def test_default_repository_cannot_be_disabled(self):
        repo = factory.make_PackageRepository(default=True)
        params = self.make_valid_repo_params(repo)
        params["enabled"] = False
        form = PackageRepositoryForm(data=params, instance=repo)
        assert not form.is_valid()
        with pytest.raises(ValidationError):
            form.clean()

    def test_create_package_repository_defaults_to_enabled(self):
        repo = factory.make_PackageRepository()
        params = self.make_valid_repo_params(repo)
        del params["enabled"]
        form = PackageRepositoryForm(data=params)
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        for key, value in params.items():
            assert getattr(package_repository, key) == value
        assert package_repository.enabled

    def test_accepts_valid_key(self):
        params = self.make_valid_repo_params()
        params["key"] = SAMPLE_GPG_PUBLIC_KEY
        form = PackageRepositoryForm(data=params)
        assert form.is_valid(), form.errors

    def test_accepts_empty_key(self):
        params = self.make_valid_repo_params()
        params["key"] = ""
        form = PackageRepositoryForm(data=params)
        assert form.is_valid(), form.errors

    def test_rejects_invalid_key(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository, data={"key": "whatever"}
        )
        assert not form.is_valid()
        assert "key" in form.errors

    def test_fail_validation_on_create_cleans_url(self):
        PackageRepository.objects.all().delete()
        repo = factory.make_PackageRepository()
        params = self.make_valid_repo_params(repo)
        params["url"] = factory.make_string()
        repo.delete()
        form = PackageRepositoryForm(data=params)
        assert not form.is_valid()
        assert not PackageRepository.objects.exists()

    def test_updates_name(self):
        package_repository = factory.make_PackageRepository()
        name = factory.make_name("name")
        form = PackageRepositoryForm(
            instance=package_repository, data={"name": name}
        )
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        assert name == package_repository.name
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == (
            "Updated package repository '%s'." % package_repository.name
        )

    def test_updates_url(self):
        package_repository = factory.make_PackageRepository()
        url = factory.make_url(scheme="http")
        form = PackageRepositoryForm(
            instance=package_repository, data={"url": url}
        )
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        assert url == package_repository.url

    def test_updates_enabled(self):
        package_repository = factory.make_PackageRepository()
        enabled = not package_repository.enabled
        form = PackageRepositoryForm(
            instance=package_repository, data={"enabled": enabled}
        )
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        assert enabled == package_repository.enabled

    def test_updates_arches(self):
        package_repository = factory.make_PackageRepository()
        arch1 = random.choice(PackageRepository.KNOWN_ARCHES)
        arch2 = random.choice(PackageRepository.KNOWN_ARCHES)
        arch3 = random.choice(PackageRepository.KNOWN_ARCHES)
        form = PackageRepositoryForm(
            instance=package_repository, data={"arches": [arch1, arch2, arch3]}
        )
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        assert [arch1, arch2, arch3] == package_repository.arches

    def test_update_failure_doesnt_delete_url(self):
        package_repository = factory.make_PackageRepository()
        url = package_repository.url
        form = PackageRepositoryForm(
            instance=package_repository,
            data={"url": factory.make_url(scheme="fake")},
        )
        assert not form.is_valid()
        assert url == reload_object(package_repository).url

    def test_creates_package_repository_defaults_main_arches(self):
        repo = factory.make_PackageRepository(arches=[])
        params = self.make_valid_repo_params(repo)
        del params["arches"]
        form = PackageRepositoryForm(data=params)
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        for key, value in params.items():
            assert getattr(package_repository, key) == value
        assert sorted(package_repository.arches) == sorted(
            PackageRepository.MAIN_ARCHES
        )

    def test_default_ports_package_repository_arches(self):
        package_repository = PackageRepository.objects.get(
            name="ports_archive"
        )
        form = PackageRepositoryForm(
            instance=package_repository, data={"arches": []}
        )
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        assert sorted(package_repository.arches) == sorted(
            PackageRepository.PORTS_ARCHES
        )

    def test_arches_validation(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository, data={"arches": ["i286"]}
        )
        assert [
            "'i286' is not a valid architecture. Known architectures: "
            "amd64, arm64, armhf, i386, ppc64el, riscv64, s390x"
        ] == form.errors.get("arches")
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        with pytest.raises(ValueError):
            form.save(endpoint, request)

    def test_arches_comma_cleaning(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository, data={"arches": ["i386,armhf"]}
        )
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        repo = form.save(endpoint, request)
        assert sorted(["i386", "armhf"]) == sorted(repo.arches)
        form = PackageRepositoryForm(
            instance=package_repository, data={"arches": ["i386, armhf"]}
        )
        repo = form.save(endpoint, request)
        assert sorted(["i386", "armhf"]) == sorted(repo.arches)
        form = PackageRepositoryForm(
            instance=package_repository, data={"arches": ["i386"]}
        )
        repo = form.save(endpoint, request)
        assert sorted(["i386"]) == sorted(repo.arches)

    def test_distribution_comma_cleaning(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository, data={"distributions": ["val1,val2"]}
        )
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        repo = form.save(endpoint, request)
        assert sorted(["val1", "val2"]) == sorted(repo.distributions)
        form = PackageRepositoryForm(
            instance=package_repository, data={"distributions": ["val1, val2"]}
        )
        repo = form.save(endpoint, request)
        assert sorted(["val1", "val2"]) == sorted(repo.distributions)
        form = PackageRepositoryForm(
            instance=package_repository, data={"distributions": ["val1"]}
        )
        repo = form.save(endpoint, request)
        assert ["val1"] == repo.distributions

    def test_disabled_pocket_comma_cleaning(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository,
            data={"disabled_pockets": ["updates,backports"]},
        )
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        repo = form.save(endpoint, request)
        assert sorted(["updates", "backports"]) == sorted(
            repo.disabled_pockets
        )
        form = PackageRepositoryForm(
            instance=package_repository,
            data={"disabled_pockets": ["updates, backports"]},
        )
        repo = form.save(endpoint, request)
        assert sorted(["updates", "backports"]) == sorted(
            repo.disabled_pockets
        )
        form = PackageRepositoryForm(
            instance=package_repository, data={"disabled_pockets": ["updates"]}
        )
        repo = form.save(endpoint, request)
        assert ["updates"] == repo.disabled_pockets

    def test_disabled_component_comma_cleaning(self):
        package_repository = factory.make_PackageRepository(
            default=True, components=[]
        )
        form = PackageRepositoryForm(
            instance=package_repository,
            data={"disabled_components": ["universe,multiverse"]},
        )
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        repo = form.save(endpoint, request)
        assert ["universe", "multiverse"] == repo.disabled_components
        form = PackageRepositoryForm(
            instance=package_repository,
            data={"disabled_components": ["universe, multiverse"]},
        )
        repo = form.save(endpoint, request)
        assert ["universe", "multiverse"] == repo.disabled_components
        form = PackageRepositoryForm(
            instance=package_repository,
            data={"disabled_components": ["universe"]},
        )
        repo = form.save(endpoint, request)
        assert ["universe"] == repo.disabled_components

    def test_component_comma_cleaning(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository, data={"components": ["val1,val2"]}
        )
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        repo = form.save(endpoint, request)
        assert sorted(["val1", "val2"]) == sorted(repo.components)
        form = PackageRepositoryForm(
            instance=package_repository, data={"components": ["val1, val2"]}
        )
        repo = form.save(endpoint, request)
        assert sorted(["val1", "val2"]) == sorted(repo.components)
        form = PackageRepositoryForm(
            instance=package_repository, data={"components": ["val1"]}
        )
        repo = form.save(endpoint, request)
        assert sorted(["val1"]) == sorted(repo.components)

    def test_updates_disable_sources(self):
        package_repository = factory.make_PackageRepository()
        form = PackageRepositoryForm(
            instance=package_repository, data={"disable_sources": True}
        )
        assert form.is_valid(), form.errors
        request = HttpRequest()
        request.user = factory.make_User()
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        package_repository = form.save(endpoint, request)
        assert package_repository.disable_sources
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == (
            "Updated package repository '%s'." % package_repository.name
        )
