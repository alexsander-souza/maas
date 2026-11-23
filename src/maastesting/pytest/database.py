# Copyright 2024-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile

from django.conf import settings
from postgresfixture import ClusterFixture
import pytest

import maasserver.testing
from maasserver.testing.resources import (
    close_all_connections,
    create_postgres_cluster,
)

cluster_stash = pytest.StashKey[ClusterFixture]()
db_template_stash = pytest.StashKey[str]()


def pytest_addoption(parser):
    default_initial_db = (
        Path(maasserver.testing.__file__).parent / "initial.maas_test.sql"
    )
    maas_parser = parser.getgroup("maas", description="MAAS")
    maas_parser.addoption(
        "--maas-recreate-initial-db",
        help="Recreate the DB template that's used to speed up tests",
        action="store_true",
    )
    maas_parser.addoption(
        "--maas-initial-db",
        help="The initial DB dump that's used to create the DB template.",
        default=str(default_initial_db),
    )


def load_initial_db_file(cluster, template_name, path):
    if path.suffix == ".sql":
        with connect(cluster) as conn:
            with conn.cursor() as cursor:
                # template0 never has sessions attached, unlike
                # template1 (the default), so this cannot fail with
                # ObjectInUse when another worker concurrently holds
                # a template1 connection (e.g. an unlocked dropdb).
                cursor.execute(
                    f'CREATE DATABASE "{template_name}" TEMPLATE template0'
                )
        cluster.execute(
            "psql",
            "--quiet",
            "--single-transaction",
            "--set=ON_ERROR_STOP=1",
            "--dbname",
            template_name,
            "--output",
            os.devnull,
            "--file",
            str(path),
        )
    else:
        # Assume it's a DB dump of the "maas" database.
        cluster.execute(
            "pg_restore",
            "-O",
            "-x",
            "--disable-triggers",
            "--create",
            "--clean",
            "--if-exists",
            "-d",
            "postgres",
            str(path),
        )
        with connect(cluster) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'ALTER DATABASE "maas" RENAME TO "{template_name}"'
                )


@contextmanager
def connect(cluster):
    conn = cluster.connect(database="postgres")
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    cluster = create_postgres_cluster()
    cluster.setUp()
    early_config.stash[cluster_stash] = cluster

    early_config.stash[db_template_stash] = "maas_test"


@pytest.hookimpl
def pytest_unconfigure(config):
    cluster = config.stash[cluster_stash]
    cluster.cleanUp()


def _set_up_template_db(
    cluster, template_name, template_path, force_recreate=False
):
    if force_recreate:
        with connect(cluster) as conn:
            with conn.cursor() as cursor:
                cursor.execute(f'DROP DATABASE IF EXISTS "{template_name}"')

    if template_name not in cluster.databases:
        load_initial_db_file(cluster, template_name, template_path)

    settings_name = "maasdjangotestsettings"
    with tempfile.TemporaryDirectory() as temp_dir:
        settings_path = Path(temp_dir) / f"{settings_name}.py"
        settings_path.write_text(
            "from maasserver.djangosettings.pytest import *\n"
            f'DATABASES["default"]["NAME"] = "{template_name}"\n'
        )
        subprocess.run(
            [
                "bin/maas-region",
                "dbupgrade",
                "--pythonpath",
                temp_dir,
                "--settings",
                settings_name,
                "--openfga-path",
                os.getcwd() + "/src/maasopenfga/build/",
            ],
            check=True,
        )

    database = settings.DATABASES["default"]
    old_name = database["NAME"]
    close_all_connections()
    settings_name = "maasdjangotestsyncdbsettings"
    with tempfile.TemporaryDirectory() as temp_dir:
        settings_path = Path(temp_dir) / f"{settings_name}.py"
        settings_path.write_text(
            "from maasserver.djangosettings.pytest import *\n"
            f'DATABASES["default"]["NAME"] = "{template_name}"\n'
            "MIGRATION_MODULES = {\n"
            "    **MIGRATION_MODULES,\n"
            '    "auth": "maastesting.empty",\n'
            '    "contenttypes": "maastesting.empty",\n'
            '    "sessions": "maastesting.empty",\n'
            '    "sites": "maastesting.empty",\n'
            '    "piston3": "maastesting.empty",\n'
            '    "maasserver": "maastesting.empty",\n'
            '    "metadataserver": "maastesting.empty",\n'
            "}\n"
        )
        subprocess.run(
            [
                "bin/maas-region",
                "migrate",
                "--run-syncdb",
                "--verbosity=0",
                "--pythonpath",
                temp_dir,
                "--settings",
                settings_name,
            ],
            check=True,
        )
    database["NAME"] = old_name


@pytest.fixture(scope="session")
def templatemaasdb(pytestconfig):
    cluster = pytestconfig.stash[cluster_stash]
    force_recreate = pytestconfig.option.maas_recreate_initial_db
    template_path = Path(pytestconfig.option.maas_initial_db)
    with cluster.lock.exclusive:
        template_name = pytestconfig.stash[db_template_stash]
        _set_up_template_db(
            cluster, template_name, template_path, force_recreate
        )


@pytest.fixture
def ensuremaasdb(request, templatemaasdb, pytestconfig, worker_id):
    template = pytestconfig.stash[db_template_stash]
    dbname = f"{template}_{worker_id}"
    cluster = pytestconfig.stash[cluster_stash]
    template = pytestconfig.stash[db_template_stash]
    with (
        cluster.lock.exclusive,
        connect(cluster) as conn,
        conn.cursor() as cursor,
    ):
        if request.node.get_closest_marker("recreate_db"):
            cursor.execute(f"DROP DATABASE IF EXISTS {dbname}")
        if dbname not in cluster.databases:
            cursor.execute(
                f'CREATE DATABASE "{dbname}" WITH TEMPLATE "{template}"'
            )
    yield dbname
