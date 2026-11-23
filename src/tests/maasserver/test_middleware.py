# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import http.client
import json
import random

from crochet import TimeoutError
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
import pytest

from maascommon.logging.security import AUTHZ_FAIL, SECURITY
from maascommon.tracing import set_trace_id
from maasserver import middleware as middleware_module
from maasserver.exceptions import MAASAPIException, MAASAPINotFound
from maasserver.middleware import (
    AccessMiddleware,
    APIRPCErrorsMiddleware,
    CSRFHelperMiddleware,
    DebuggingLoggerMiddleware,
    ExceptionMiddleware,
    is_public_path,
    RPCErrorsMiddleware,
    TracingMiddleware,
)
from maasserver.testing import extract_redirect
from maasserver.testing.factory import factory
from maasserver.utils.orm import (
    make_deadlock_failure,
    make_serialization_failure,
)
from maastesting.utils import sample_binary_data
from provisioningserver.rpc.exceptions import NoConnectionsAvailable
from provisioningserver.utils.shell import ExternalProcessError


@pytest.mark.usefixtures("maasdb")
class TestIsPublicPath:
    def test_public_path(self):
        assert is_public_path("/MAAS/accounts/login/")
        assert is_public_path("/MAAS/rpc/someurl")

    def test_path_not_public(self):
        assert not (is_public_path("/"))
        assert not (is_public_path("/MAAS/"))


@pytest.mark.usefixtures("maasdb", "factory")
class TestTracingMiddleware:
    @pytest.fixture(autouse=True)
    def _reset_trace_id(self):
        yield
        set_trace_id("")

    def process_request(self, request, response=None):
        def get_response(_):
            if response:
                return response
            else:
                return HttpResponse(status=200)

        middleware = TracingMiddleware(get_response)
        return middleware(request)

    def test_trace_id_is_taken_from_request(self):
        request = factory.make_fake_request(
            "/", headers={"MAAS-trace-id": "my-trace-id"}
        )
        assert (
            self.process_request(request).headers["MAAS-trace-id"]
            == "my-trace-id"
        )

    def test_trace_id_is_taken_from_context(self):
        set_trace_id("existing-trace-id")
        request = factory.make_fake_request("/")
        assert (
            self.process_request(request).headers["MAAS-trace-id"]
            == "existing-trace-id"
        )


@pytest.mark.usefixtures("maasdb", "factory")
class TestAccessMiddleware:
    def process_request(self, request, response=None):
        def get_response(request):
            if response:
                return response
            else:
                return HttpResponse(status=200)

        middleware = AccessMiddleware(get_response)
        return middleware(request)

    def test_return_request_on_public_path(self):
        request = factory.make_fake_request("/MAAS/accounts/login/")
        assert self.process_request(request).status_code == http.client.OK

    def test_return_redirect_index(self):
        request = factory.make_fake_request("/MAAS/")
        request.user = AnonymousUser()
        assert extract_redirect(self.process_request(request)) == "/MAAS/"


@pytest.mark.usefixtures("maasdb", "factory")
class TestExceptionMiddleware:
    def make_base_path(self):
        """Return a path to handle exceptions for."""
        return "/%s" % factory.make_string()

    def make_fake_request(self):
        return factory.make_fake_request(self.make_base_path())

    def process_exception(self, request, exception):
        def get_response(request):
            raise exception

        middleware = ExceptionMiddleware(get_response)
        return middleware(request)

    def test_ignores_serialization_failures(self):
        request = self.make_fake_request()
        exception = make_serialization_failure()
        with pytest.raises(type(exception)):
            self.process_exception(request, exception)

    def test_ignores_deadlock_failures(self):
        request = self.make_fake_request()
        exception = make_deadlock_failure()
        with pytest.raises(type(exception)):
            self.process_exception(request, exception)

    def test_unknown_exception_generates_internal_server_error(self):
        # An unknown exception generates an internal server error with the
        # exception message.
        request = self.make_fake_request()
        error_message = factory.make_string()
        response = self.process_exception(request, RuntimeError(error_message))
        assert isinstance(response.content, bytes)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.INTERNAL_SERVER_ERROR, error_message)

    def test_reports_MAASAPIException_with_appropriate_api_error(self):
        class MyException(MAASAPIException):
            api_error = int(http.client.UNAUTHORIZED)

        error_message = factory.make_string()
        exception = MyException(error_message)
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert isinstance(response.content, bytes)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.UNAUTHORIZED, error_message)

    def test_renders_MAASAPIException_as_unicode(self):
        class MyException(MAASAPIException):
            api_error = int(http.client.UNAUTHORIZED)

        error_message = "Error %s" % chr(233)
        exception = MyException(error_message)
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.UNAUTHORIZED, error_message)

    def test_reports_ValidationError_as_Bad_Request(self):
        error_message = factory.make_string()
        exception = ValidationError(error_message)
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert isinstance(response.content, bytes)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.BAD_REQUEST, error_message)

    def test_returns_ValidationError_message_dict_as_json(self):
        exception_dict = {"hostname": ["invalid"]}
        exception = ValidationError(exception_dict)
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert isinstance(response.content, bytes)
        assert (
            json.loads(response.content.decode(settings.DEFAULT_CHARSET))
            == exception_dict
        )
        assert "application/json" in response["Content-Type"]

    def test_reports_PermissionDenied_as_Forbidden(self):
        error_message = factory.make_string()
        exception = PermissionDenied(error_message)
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert isinstance(response.content, bytes)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.FORBIDDEN, error_message)

    def test_PermissionDenied_creates_log(self, mocker):
        logger = mocker.patch.object(middleware_module, "logger")
        error_message = factory.make_string()
        exception = PermissionDenied(error_message)
        request = self.make_fake_request()
        request.user = factory.make_User()
        self.process_exception(request, exception)
        logger.warn.assert_called_once_with(
            AUTHZ_FAIL,
            type=SECURITY,
            user_id=request.user.username,
            role=middleware_module.ADMIN
            if request.user.is_superuser
            else middleware_module.USER,
            useragent=request.META.get("HTTP_USER_AGENT", "unknown"),
            request_remote_ip=request.META.get("REMOTE_ADDR", "unknown"),
            request_path=request.path,
            request_method=request.method,
        )

    def test_api_500_error_is_logged(self, mocker):
        logger = mocker.patch.object(middleware_module, "logger")
        error_text = factory.make_string()
        exception = MAASAPIException(error_text)
        request = self.make_fake_request()
        self.process_exception(request, exception)
        logger.error.assert_called()
        args, _ = logger.error.call_args
        assert error_text in args[0]

    def test_generic_500_error_is_logged(self, mocker):
        logger = mocker.patch.object(middleware_module, "logger")
        error_text = factory.make_string()
        exception = Exception(error_text)
        request = self.make_fake_request()
        self.process_exception(request, exception)
        logger.error.assert_called()
        args, _ = logger.error.call_args
        assert error_text in args[0]

    def test_reports_ExternalProcessError_as_ServiceUnavailable(self, mocker):
        error_text = factory.make_string()
        exception = ExternalProcessError(1, ["cmd"], error_text)
        retry_after = random.randint(0, 10)
        mocker.patch.object(
            middleware_module, "RETRY_AFTER_SERVICE_UNAVAILABLE", retry_after
        )
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert http.client.SERVICE_UNAVAILABLE == response.status_code
        assert str(exception) == response.content.decode(
            settings.DEFAULT_CHARSET
        )
        assert str(retry_after) == response["Retry-After"]

    def test_handles_error_on_API(self):
        error_message = factory.make_string()
        exception = MAASAPINotFound(error_message)
        request = self.make_fake_request()
        response = self.process_exception(request, exception)
        assert isinstance(response.content, bytes)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.NOT_FOUND, error_message)

    def test_503_response_includes_retry_after_header(self):
        error = ExternalProcessError(returncode=-1, cmd="foo-bar")
        request = self.make_fake_request()
        response = self.process_exception(request, error)
        assert (response.status_code, response["Retry-after"]) == (
            http.client.SERVICE_UNAVAILABLE,
            "%s" % middleware_module.RETRY_AFTER_SERVICE_UNAVAILABLE,
        )


@pytest.mark.usefixtures("maasdb", "factory")
class TestDebuggingLoggerMiddleware:
    def process_request(self, request, response=None):
        def get_response(request):
            if response:
                return response
            else:
                return HttpResponse(status=200)

        middleware = DebuggingLoggerMiddleware(get_response)
        return middleware(request)

    def test_debugging_logger_does_not_log_response_if_no_debug_http(
        self, mocker
    ):
        logger = mocker.patch.object(middleware_module, "logger")
        request = factory.make_fake_request("/MAAS/api/2.0/nodes/")
        response = HttpResponse(
            content="test content", content_type=b"text/plain; charset=utf-8"
        )
        self.process_request(request, response)
        logger.debug.assert_not_called()
        logger.info.assert_not_called()

    def test_debugging_logger_logs_request(self, mocker):
        mocker.patch.object(settings, "DEBUG_HTTP", True)
        logger = mocker.patch.object(middleware_module, "logger")
        request = factory.make_fake_request("/MAAS/api/2.0/nodes/")
        request.content = "test content"
        self.process_request(request)
        debug_output = DebuggingLoggerMiddleware._build_request_repr(request)
        calls = logger.debug.call_args_list
        assert debug_output in calls[0][0][0]

    def test_debugging_logger_logs_response(self, mocker):
        mocker.patch.object(settings, "DEBUG_HTTP", True)
        logger = mocker.patch.object(middleware_module, "logger")
        request = factory.make_fake_request("foo")
        response = HttpResponse(
            content="test content", content_type=b"text/plain; charset=utf-8"
        )
        self.process_request(request, response)
        calls = logger.debug.call_args_list
        assert (
            response.content.decode(settings.DEFAULT_CHARSET) in calls[1][0][0]
        )

    def test_debugging_logger_logs_binary_response(self, mocker):
        mocker.patch.object(settings, "DEBUG_HTTP", True)
        logger = mocker.patch.object(middleware_module, "logger")
        request = factory.make_fake_request("foo")
        response = HttpResponse(
            content=sample_binary_data,
            content_type=b"application/octet-stream",
        )
        self.process_request(request, response)
        calls = logger.debug.call_args_list
        assert "non-utf-8 (binary?) content" in calls[1][0][0]


@pytest.mark.usefixtures("maasdb", "factory")
class TestRPCErrorsMiddleware:
    def process_request(self, request, exception=None):
        def get_response(request):
            if exception:
                raise exception
            else:
                return None

        middleware = RPCErrorsMiddleware(get_response)
        return middleware(request)

    def test_handles_NoConnectionsAvailable(self):
        request = factory.make_fake_request(factory.make_string(), "POST")
        error_message = (
            "No connections available for cluster %s"
            % factory.make_name("cluster")
        )
        error = NoConnectionsAvailable(error_message)
        response = self.process_request(request, error)

        # The response is a redirect.
        assert extract_redirect(response) == request.path

    def test_handles_TimeoutError(self):
        request = factory.make_fake_request(factory.make_string(), "POST")
        error_message = "Here, have a picture of Queen Victoria!"
        error = TimeoutError(error_message)
        response = self.process_request(request, error)

        # The response is a redirect.
        assert extract_redirect(response) == request.path

    def test_ignores_non_rpc_errors(self):
        request = factory.make_fake_request(factory.make_string(), "POST")
        exception = ZeroDivisionError(
            "You may think it's a long walk down the street to the chemist "
            "but that's just peanuts to space!"
        )
        with pytest.raises(ZeroDivisionError):
            self.process_request(request, exception)

    def test_ignores_error_on_API(self):
        non_api_request = factory.make_fake_request("/MAAS/api/2.0/ohai")
        exception_class = NoConnectionsAvailable
        exception = exception_class(factory.make_string())
        with pytest.raises(exception_class):
            self.process_request(non_api_request, exception)

    def test_no_connections_available_has_usable_cluster_name_in_msg(self):
        # If a NoConnectionsAvailable exception carries a reference to
        # the cluster UUID, RPCErrorsMiddleware will look up the
        # cluster's name and make the error message it displays more
        # useful.
        request = factory.make_fake_request(factory.make_string(), "POST")
        rack_controller = factory.make_RackController()
        error = NoConnectionsAvailable(
            factory.make_name("msg"), uuid=rack_controller.system_id
        )
        self.process_request(request, error)


@pytest.mark.usefixtures("maasdb", "factory")
class TestAPIRPCErrorsMiddleware:
    def process_request(self, request, exception=None):
        def get_response(request):
            if exception:
                raise exception
            else:
                return None

        middleware = APIRPCErrorsMiddleware(get_response)
        return middleware(request)

    def test_handles_error_on_API(self):
        middleware = APIRPCErrorsMiddleware(lambda request: None)
        api_request = factory.make_fake_request("/MAAS/api/2.0/hello")
        error_message = factory.make_string()
        exception_class = NoConnectionsAvailable
        exception = exception_class(error_message)
        response = self.process_request(api_request, exception)
        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (middleware.handled_exceptions[exception_class], error_message)

    def test_ignores_error_outside_API(self):
        non_api_request = factory.make_fake_request(
            "/MAAS/middleware/api/hello"
        )
        exception_class = NoConnectionsAvailable
        exception = exception_class(factory.make_string())
        with pytest.raises(exception_class):
            self.process_request(non_api_request, exception)

    def test_no_connections_available_returned_as_503(self):
        request = factory.make_fake_request(
            "/MAAS/api/2.0/" + factory.make_string(), "POST"
        )
        error_message = (
            "Unable to connect to cluster '%s'; no connections available"
            % factory.make_name("cluster")
        )
        error = NoConnectionsAvailable(error_message)
        response = self.process_request(request, error)

        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.SERVICE_UNAVAILABLE, error_message)

    def test_503_response_includes_retry_after_header_by_default(self):
        request = factory.make_fake_request(
            "/MAAS/api/2.0/" + factory.make_string(), "POST"
        )
        error = NoConnectionsAvailable(factory.make_name())
        response = self.process_request(request, error)

        assert (response.status_code, response["Retry-after"]) == (
            http.client.SERVICE_UNAVAILABLE,
            "%s" % middleware_module.RETRY_AFTER_SERVICE_UNAVAILABLE,
        )

    def test_handles_TimeoutError(self):
        request = factory.make_fake_request(
            "/MAAS/api/2.0/" + factory.make_string(), "POST"
        )
        error_message = "No thanks, I'm trying to give them up."
        error = TimeoutError(error_message)
        response = self.process_request(request, error)

        assert (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        ) == (http.client.GATEWAY_TIMEOUT, error_message)

    def test_ignores_non_rpc_errors(self):
        request = factory.make_fake_request(
            "/MAAS/api/2.0/" + factory.make_string(), "POST"
        )
        exception = ZeroDivisionError(
            "You may think it's a long walk down the street to the chemist "
            "but that's just peanuts to space!"
        )
        with pytest.raises(ZeroDivisionError):
            self.process_request(request, exception)


@pytest.mark.usefixtures("maasdb")
class TestCSRFHelperMiddleware:
    def process_request(self, request):
        def get_response(request):
            return None

        middleware = CSRFHelperMiddleware(get_response)
        return middleware(request)

    def test_sets_csrf_exception_if_no_session_cookie(self):
        cookies = {}
        request = factory.make_fake_request(
            factory.make_string(), "GET", cookies=cookies
        )
        self.process_request(request)
        assert getattr(request, "csrf_processing_done", None)

    def test_doesnt_set_csrf_exception_if_session_cookie(self):
        cookies = {settings.SESSION_COOKIE_NAME: factory.make_name("session")}
        request = factory.make_fake_request(
            factory.make_string(), "GET", cookies=cookies
        )
        self.process_request(request)
        assert getattr(request, "csrf_processing_done", None) is None
