# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Self-contained test-resource managers used by pytest database fixtures.

This replaces the `testresources` manager contract. Nose-specific result
reporting and unittest `setUpResources`/`tearDownResources` adapters are not
part of the pytest resource-manager API.
"""

__all__ = ["TestResourceManager"]


class TestResourceManager:
    """Manage a single reusable resource, with reference counting.

    Subclasses override `make` to construct the resource and `clean` to
    tear it down. Dependencies are declared as a class-level `resources`
    list of `(name, manager)` tuples; dependency resources are built
    before and cleaned after the managed resource, and attached to it as
    attributes named by `name`.
    """

    resources = []

    def __init__(self):
        self._dirty = False
        self._uses = 0
        self._currentResource = None
        self.resources = list(getattr(self.__class__, "resources", []))

    # -- subclass hooks -------------------------------------------------

    def make(self, dependency_resources):
        """Construct and return the resource. Override in subclasses."""
        raise NotImplementedError("Override make to construct resources.")

    def clean(self, resource):
        """Tear down the resource. Override in subclasses."""

    # -- dependency-aware build/clean -----------------------------------

    def _make_all(self):
        dependency_resources = {}
        for name, manager in self.resources:
            dependency_resources[name] = manager.getResource()
        resource = self.make(dependency_resources)
        for name, value in dependency_resources.items():
            setattr(resource, name, value)
        return resource

    def _clean_all(self, resource):
        self.clean(resource)
        for name, manager in self.resources:
            manager.finishedWith(getattr(resource, name))

    def _reset(self, resource, dependency_resources):
        self.clean(resource)
        return self.make(dependency_resources)

    def _setResource(self, new_resource):
        self._currentResource = new_resource
        self._dirty = False

    # -- dirtiness ------------------------------------------------------

    def dirtied(self, resource):
        """Mark the current resource unsuitable for reuse by other tests."""
        self._dirty = True

    def isDirty(self):
        if self._dirty:
            return True
        for _name, manager in self.resources:
            if manager.isDirty():
                return True
        return False

    def reset(self, old_resource):
        """Return a clean version of a dirty resource."""
        if not self.isDirty():
            return old_resource
        dependency_resources = {}
        for name, manager in self.resources:
            dependency_resources[name] = manager.reset(
                getattr(old_resource, name)
            )
        resource = self._reset(old_resource, dependency_resources)
        for name, value in dependency_resources.items():
            setattr(resource, name, value)
        return resource

    # -- reference counting ---------------------------------------------

    def getResource(self):
        """Return the resource, building/resetting it if needed."""
        if self._uses == 0:
            self._setResource(self._make_all())
        elif self.isDirty():
            self._setResource(self.reset(self._currentResource))
        self._uses += 1
        return self._currentResource

    def finishedWith(self, resource):
        """Record one fewer user; clean the resource when it reaches zero."""
        self._uses -= 1
        if self._uses == 0:
            self._clean_all(resource)
            self._setResource(None)
