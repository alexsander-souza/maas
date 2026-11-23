import logging

from maasserver.enum import NODE_STATUS
from maasserver.utils.orm import post_commit_hooks


def test_node_mark_failed_deployment_logs_failure(factory, caplog, mocker):
    mocker.patch("maasserver.models.node.stop_workflow")
    node = factory.make_Node(
        status=NODE_STATUS.DEPLOYING, with_boot_disk=False
    )
    with caplog.at_level(logging.DEBUG, logger="maas.node"):
        with post_commit_hooks:
            node.mark_failed()
    assert node.status == NODE_STATUS.FAILED_DEPLOYMENT
    record_tuple = (
        "maas.node",
        logging.DEBUG,
        f"Node '{node.hostname}' failed deployment",
    )

    assert record_tuple in caplog.record_tuples
