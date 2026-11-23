# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.testing`."""

from django.db.models.signals import post_save, pre_save
from django.http import HttpResponse, HttpResponseRedirect
import pytest

from maasserver.models.node import Node
from maasserver.testing import extract_redirect, NoReceivers
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_objects
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestHelpers:
    """Test helper functions."""

    def test_extract_redirect_extracts_redirect_location(self):
        url = factory.make_string()
        assert url == extract_redirect(HttpResponseRedirect(url))

    def test_extract_redirect_only_returns_target_path(self):
        url_path = factory.make_string()
        assert f"/{url_path}" == extract_redirect(
            HttpResponseRedirect(f"http://example.com/{url_path}")
        )

    def test_extract_redirect_errors_out_helpfully_if_not_a_redirect(self):
        content = factory.make_string(10).encode("ascii")
        other_response = HttpResponse(content=content)
        with pytest.raises(
            ValueError,
            match=f"Not a redirect: http status 200. Content: {content}",
        ):
            extract_redirect(other_response)

    def test_reload_object_reloads_object(self):
        test_obj = factory.make_Node()
        test_obj.save()
        Node.objects.filter(id=test_obj.id).update(hostname="newname")
        assert "newname" == reload_object(test_obj).hostname

    def test_reload_object_returns_None_for_deleted_object(self):
        test_obj = factory.make_Node()
        test_obj.save()
        Node.objects.filter(id=test_obj.id).delete()
        assert reload_object(test_obj) is None

    def test_reload_objects_reloads_objects(self):
        hostnames = ["name1", "name2", "name3"]
        objs = [factory.make_Node(hostname=hostname) for hostname in hostnames]
        for obj in objs:
            obj.save()
        hostnames[0] = "different"
        Node.objects.filter(id=objs[0].id).update(hostname=hostnames[0])
        assert ["different", "name2", "name3"] == sorted(
            obj.hostname for obj in reload_objects(Node, objs)
        )

    def test_reload_objects_omits_deleted_objects(self):
        objs = [factory.make_Node() for counter in range(3)]
        for obj in objs:
            obj.save()
        dead_obj = objs.pop(0)
        Node.objects.filter(id=dead_obj.id).delete()
        assert {obj.id for obj in objs} == {
            obj.id for obj in reload_objects(Node, objs)
        }


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNoReceivers:
    def test_clears_and_restores_signal(self):
        # post_save already has some receivers on it, but make sure.
        assert len(post_save.receivers) != 0
        old_values = list(post_save.receivers)

        with NoReceivers(post_save):
            assert [] == post_save.receivers

        assert sorted(old_values) == sorted(post_save.receivers)

    def test_clears_and_restores_many_signals(self):
        assert len(post_save.receivers) != 0
        assert len(pre_save.receivers) != 0
        old_pre_values = pre_save.receivers
        old_post_values = post_save.receivers

        with NoReceivers((post_save, pre_save)):
            assert [] == post_save.receivers
            assert [] == pre_save.receivers

        assert sorted(old_pre_values) == sorted(pre_save.receivers)
        assert sorted(old_post_values) == sorted(post_save.receivers)

    def test_leaves_some_other_signals_alone(self):
        assert len(post_save.receivers) != 0

        old_pre_values = pre_save.receivers

        with NoReceivers(post_save):
            assert sorted(old_pre_values) == sorted(pre_save.receivers)
