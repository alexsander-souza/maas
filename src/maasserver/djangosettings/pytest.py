# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Django settings for the ordinary pytest suite."""

from copy import deepcopy

from maasserver.djangosettings import development, import_settings

import_settings(development)

INSTALLED_APPS = (
    *development.INSTALLED_APPS,
    "maasserver.tests.apps.MAASServerTestsConfig",
    "metadataserver.tests.apps.MetadataServerTestsConfig",
)
MIGRATION_MODULES = {
    **development.MIGRATION_MODULES,
    "maasserver_tests": None,
    "metadataserver_tests": None,
}
DATABASES = deepcopy(development.DATABASES)
