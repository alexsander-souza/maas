# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for custom metadata field types."""

from base64 import b64encode

import pytest

from maastesting.factory import factory
from metadataserver.fields import Bin, BinaryField
from metadataserver.tests.models import BinaryFieldModel


class TestBin:
    """Test Bin helper class."""

    def test_is_basically_bytes(self):
        assert Bin(b"Hello") == b"Hello"

    def test_refuses_to_construct_from_unicode(self):
        with pytest.raises(AssertionError):
            Bin("Hello")

    def test_refuses_to_construct_from_None(self):
        with pytest.raises(AssertionError):
            Bin(None)

    def test_emits_base64(self):
        # Piston hooks onto an __emittable__() method, if present.
        # Bin() returns a base-64 encoded string so that it can be
        # transmitted in JSON.
        assert Bin(b"").__emittable__() == ""
        example_bytes = factory.make_bytes()
        assert Bin(example_bytes).__emittable__() == b64encode(
            example_bytes
        ).decode("ascii")


@pytest.mark.usefixtures("maasdb")
class TestBinaryField:
    """Test BinaryField. Uses BinaryFieldModel test model."""

    def test_stores_and_retrieves_None(self):
        binary_item = BinaryFieldModel()
        assert binary_item.data is None
        binary_item.save()
        assert BinaryFieldModel.objects.get(id=binary_item.id).data is None

    def test_stores_and_retrieves_empty_data(self):
        binary_item = BinaryFieldModel(data=Bin(b""))
        binary_item.save()
        assert Bin(b"") == BinaryFieldModel.objects.get(id=binary_item.id).data

    def test_does_not_truncate_at_zero_bytes(self):
        data = b"BEFORE THE ZERO\x00AFTER THE ZERO"
        binary_item = BinaryFieldModel(data=Bin(data))
        binary_item.save()
        assert data == BinaryFieldModel.objects.get(id=binary_item.id).data

    def test_stores_and_retrieves_binary_data(self):
        data = b"\x01\x02\xff\xff\xfe\xff\xff\xfe"
        binary_item = BinaryFieldModel(data=Bin(data))
        binary_item.save()
        assert data == BinaryFieldModel.objects.get(id=binary_item.id).data

    def test_returns_bytes_not_text(self):
        binary_item = BinaryFieldModel(data=Bin(b"Data"))
        binary_item.save()
        retrieved_data = BinaryFieldModel.objects.get(id=binary_item.id).data
        assert isinstance(retrieved_data, bytes)

    def test_looks_up_data(self):
        data = b"Binary item"
        binary_item = BinaryFieldModel(data=Bin(data))
        binary_item.save()
        assert binary_item == BinaryFieldModel.objects.get(data=Bin(data))

    def test_get_default_returns_None(self, mocker):
        field = BinaryField(null=True)
        mocker.patch.object(field, "default", None)
        assert field.get_default() is None

    def test_get_default_returns_Bin(self, mocker):
        field = BinaryField(null=True)
        mocker.patch.object(field, "default", Bin(b"wotcha"))
        assert Bin(b"wotcha") == field.get_default()

    def test_get_default_returns_Bin_from_bytes(self, mocker):
        field = BinaryField(null=True)
        mocker.patch.object(field, "default", b"wotcha")
        assert Bin(b"wotcha") == field.get_default()
