# This software is licensed under the MIT license.
#
# Copyright (c) Twisted Matrix Laboratories.
#               2015-2018 Canonical Ltd.
#
# http://twistedmatrix.com/trac/ticket/4173

"""
The WebSockets Protocol, according to RFC 6455
(http://tools.ietf.org/html/rfc6455). When "RFC" is mentioned, it refers to
this RFC. Some tests reference HyBi-10
(http://tools.ietf.org/html/draft-ietf-hybi-thewebsocketprotocol-10) or
HyBi-07 (http://tools.ietf.org/html/draft-ietf-hybi-thewebsocketprotocol-07),
which are drafts of RFC 6455.
"""

import pytest
from twisted.internet.address import IPv6Address
from twisted.internet.protocol import Factory, Protocol
from twisted.internet.testing import (
    AccumulatingProtocol,
    StringTransportWithDisconnection,
)
from twisted.protocols.tls import TLSMemoryBIOProtocol
from twisted.web.http_headers import Headers
from twisted.web.resource import IResource, Resource
from twisted.web.server import NOT_DONE_YET, Request
from twisted.web.test.test_web import DummyChannel
from twisted.web.test.test_web import DummyRequest as DummyRequestBase
from zope.interface import implementer
from zope.interface.verify import verifyObject

from maasserver.websockets.websockets import (
    _makeAccept,
    _makeFrame,
    _mask,
    _parseFrames,
    _WSException,
    CONTROLS,
    IWebSocketsFrameReceiver,
    lookupProtocolForFactory,
    STATUSES,
    WebSocketsProtocol,
    WebSocketsProtocolWrapper,
    WebSocketsResource,
    WebSocketsTransport,
)
from maastesting.twisted import TwistedLoggerFixture


class DummyRequest(DummyRequestBase):
    content = None

    def _cleanup(self):
        """Called to cleanup the request."""
        pass


class TestFrameHelpers:
    """
    Test functions helping building and parsing WebSockets frames.
    """

    def test_makeAcceptRFC(self):
        """
        L{_makeAccept} makes responses according to the RFC.
        """
        key = b"dGhlIHNhbXBsZSBub25jZQ=="
        assert _makeAccept(key) == b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

    def test_maskNoop(self):
        """
        Blank keys perform a no-op mask.
        """
        key = b"\x00\x00\x00\x00"
        assert _mask(b"Test", key) == b"Test"

    def test_maskNoopLong(self):
        """
        Blank keys perform a no-op mask regardless of the length of the input.
        """
        key = b"\x00\x00\x00\x00"
        assert _mask(b"LongTest", key) == b"LongTest"

    def test_maskNoopOdd(self):
        """
        Masking works even when the data to be masked isn't a multiple of four
        in length.
        """
        key = b"\x00\x00\x00\x00"
        assert _mask(b"LongestTest", key) == b"LongestTest"

    def test_maskHello(self):
        """
        A sample mask for "Hello" according to RFC 6455, 5.7.
        """
        key = b"\x37\xfa\x21\x3d"
        assert _mask(b"Hello", key) == b"\x7f\x9f\x4d\x51\x58"

    def test_parseUnmaskedText(self):
        """
        A sample unmasked frame of "Hello" from HyBi-10, 4.7.
        """
        frame = [b"\x81\x05Hello"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.TEXT, b"Hello", True)
        assert frame == []

    def test_parseUnmaskedLargeText(self):
        """
        L{_parseFrames} handles frame with text longer than 125 bytes.
        """
        frame = [b"\x81\x7e\x00\xc8", b"x" * 200]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.TEXT, b"x" * 200, True)
        assert frame == []

    def test_parseUnmaskedTextWithMaskNeeded(self):
        """
        L{_parseFrames} raises L{_WSException} if the frame is not masked and
        C{needMask} is set to C{True}.
        """
        frame = [b"\x81\x05Hello"]
        with pytest.raises(_WSException) as excinfo:
            list(_parseFrames(frame, needMask=True))
        assert "Received data not masked" == str(excinfo.value)

    def test_parseUnmaskedHugeText(self):
        """
        L{_parseFrames} handles frame with text longer than 64 kB.
        """
        frame = [b"\x81\x7f\x00\x00\x00\x00\x00\x01\x86\xa0", b"x" * 100000]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.TEXT, b"x" * 100000, True)
        assert frame == []

    def test_parseMaskedText(self):
        """
        A sample masked frame of "Hello" from HyBi-10, 4.7.
        """
        frame = [b"\x81\x857\xfa!=\x7f\x9fMQX"]
        frames = list(_parseFrames(frame))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.TEXT, b"Hello", True)
        assert frame == []

    def test_parseMaskedPartialText(self):
        """
        L{_parseFrames} stops parsing if a masked frame isn't long enough to
        contain the length of the text.
        """
        frame = [b"\x81\x827\xfa"]
        frames = list(_parseFrames(frame))
        assert len(frames) == 0
        assert frame == [b"\x81\x827\xfa"]

    def test_parseUnmaskedTextFragments(self):
        """
        Fragmented masked packets are handled.

        From HyBi-10, 4.7.
        """
        frame = [b"\x01\x03Hel\x80\x02lo"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 2
        assert frames[0] == (CONTROLS.TEXT, b"Hel", False)
        assert frames[1] == (CONTROLS.CONTINUE, b"lo", True)
        assert frame == []

    def test_parsePing(self):
        """
        Ping packets are decoded.

        From HyBi-10, 4.7.
        """
        frame = [b"\x89\x05Hello"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.PING, b"Hello", True)
        assert frame == []

    def test_parsePong(self):
        """
        Pong packets are decoded.

        From HyBi-10, 4.7.
        """
        frame = [b"\x8a\x05Hello"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.PONG, b"Hello", True)
        assert frame == []

    def test_parseCloseEmpty(self):
        """
        A HyBi-07 close packet may have no body. In that case, it decodes with
        the generic error code 1000, and has no particular justification or
        error message.
        """
        frame = [b"\x88\x00"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (CONTROLS.CLOSE, (STATUSES.NONE, b""), True)
        assert frame == []

    def test_parseCloseReason(self):
        """
        A HyBi-07 close packet must have its first two bytes be a numeric
        error code, and may optionally include trailing text explaining why
        the connection was closed.
        """
        frame = [b"\x88\x0b\x03\xe8No reason"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 1
        assert frames[0] == (
            CONTROLS.CLOSE,
            (STATUSES.NORMAL, b"No reason"),
            True,
        )
        assert frame == []

    def test_parsePartialNoLength(self):
        """
        Partial frames are stored for later decoding.
        """
        frame = [b"\x81"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 0
        assert frame == [b"\x81"]

    def test_parsePartialTruncatedLengthInt(self):
        """
        Partial frames are stored for later decoding, even if they are cut on
        length boundaries.
        """
        frame = [b"\x81\xfe"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 0
        assert frame == [b"\x81\xfe"]

    def test_parsePartialTruncatedLengthDouble(self):
        """
        Partial frames are stored for later decoding, even if they are marked
        as being extra-long.
        """
        frame = [b"\x81\xff"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 0
        assert frame == [b"\x81\xff"]

    def test_parsePartialNoData(self):
        """
        Partial frames with full headers but no data are stored for later
        decoding.
        """
        frame = [b"\x81\x05"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 0
        assert frame == [b"\x81\x05"]

    def test_parsePartialTruncatedData(self):
        """
        Partial frames with full headers and partial data are stored for later
        decoding.
        """
        frame = [b"\x81\x05Hel"]
        frames = list(_parseFrames(frame, needMask=False))
        assert len(frames) == 0
        assert frame == [b"\x81\x05Hel"]

    def test_parseReservedFlag(self):
        """
        L{_parseFrames} raises a L{_WSException} error when the header uses a
        reserved flag.
        """
        frame = [b"\x72\x05"]
        with pytest.raises(_WSException) as excinfo:
            list(_parseFrames(frame))
        assert "Reserved flag in frame (114)" == str(excinfo.value)

    def test_parseUnknownOpcode(self):
        """
        L{_parseFrames} raises a L{_WSException} error when the error uses an
        unknown opcode.
        """
        frame = [b"\x8f\x05"]
        with pytest.raises(_WSException) as excinfo:
            list(_parseFrames(frame))
        assert "Unknown opcode 15 in frame" == str(excinfo.value)

    def test_makeHello(self):
        """
        L{_makeFrame} makes valid HyBi-07 packets.
        """
        frame = b"\x81\x05Hello"
        buf = _makeFrame(b"Hello", CONTROLS.TEXT, True)
        assert frame == buf

    def test_makeLargeFrame(self):
        """
        L{_makeFrame} prefixes the payload by the length on 2 bytes if the
        payload is more than 125 bytes.
        """
        frame = b"\x81\x7e\x00\xc8" + b"x" * 200
        buf = _makeFrame(b"x" * 200, CONTROLS.TEXT, True)
        assert frame == buf

    def test_makeHugeFrame(self):
        """
        L{_makeFrame} prefixes the payload by the length on 8 bytes if the
        payload is more than 64 kB.
        """
        frame = b"\x81\x7f\x00\x00\x00\x00\x00\x01\x86\xa0" + b"x" * 100000
        buf = _makeFrame(b"x" * 100000, CONTROLS.TEXT, True)
        assert frame == buf

    def test_makeNonFinFrame(self):
        """
        L{_makeFrame} can build fragmented frames.
        """
        frame = b"\x01\x05Hello"
        buf = _makeFrame(b"Hello", CONTROLS.TEXT, False)
        assert frame == buf

    def test_makeMaskedFrame(self):
        """
        L{_makeFrame} can build masked frames.
        """
        frame = b"\x81\x857\xfa!=\x7f\x9fMQX"
        buf = _makeFrame(b"Hello", CONTROLS.TEXT, True, mask=b"7\xfa!=")
        assert frame == buf


@implementer(IWebSocketsFrameReceiver)
class SavingEchoReceiver:
    """
    A test receiver saving the data received and sending it back.
    """

    def makeConnection(self, transport):
        self.transport = transport
        self.received = []

    def frameReceived(self, opcode, data, fin):
        self.received.append((opcode, data, fin))
        if opcode == CONTROLS.TEXT:
            self.transport.sendFrame(opcode, data, fin)


class TestWebSocketsProtocol:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.receiver = SavingEchoReceiver()
        self.protocol = WebSocketsProtocol(self.receiver)
        self.factory = Factory.forProtocol(lambda: self.protocol)
        self.transport = StringTransportWithDisconnection()
        self.protocol.makeConnection(self.transport)
        self.transport.protocol = self.protocol

    def test_frameReceived(self):
        """
        L{WebSocketsProtocol.dataReceived} translates bytes into frames, and
        then write it back encoded into frames.
        """
        self.protocol.dataReceived(
            _makeFrame(b"Hello", CONTROLS.TEXT, True, mask=b"abcd")
        )
        assert b"\x81\x05Hello" == self.transport.value()
        assert [(CONTROLS.TEXT, b"Hello", True)] == self.receiver.received

    def test_ping(self):
        """
        When a C{PING} frame is received, the frame is resent with a C{PONG},
        and the application receiver is notified about it.
        """
        self.protocol.dataReceived(
            _makeFrame(b"Hello", CONTROLS.PING, True, mask=b"abcd")
        )
        assert b"\x8a\x05Hello" == self.transport.value()
        assert [(CONTROLS.PING, b"Hello", True)] == self.receiver.received

    def test_close(self):
        """
        When a C{CLOSE} frame is received, the protocol closes the connection
        and logs a message.
        """
        with TwistedLoggerFixture() as logger:
            self.protocol.dataReceived(
                _makeFrame(b"", CONTROLS.CLOSE, True, mask=b"abcd")
            )
        assert not self.transport.connected
        assert ["Closing connection: <STATUSES=NONE>"] == logger.messages

    def test_invalidFrame(self):
        """
        If an invalid frame is received, L{WebSocketsProtocol} closes the
        connection.
        """
        self.protocol.dataReceived(b"\x72\x05")
        assert not self.transport.connected


class TestWebSocketsTransport:
    def test_loseConnection(self):
        """
        L{WebSocketsTransport.loseConnection} sends a close frame and closes
        the transport afterwards.
        """
        transport = StringTransportWithDisconnection()
        transport.protocol = Protocol()
        webSocketsTranport = WebSocketsTransport(transport)
        webSocketsTranport.loseConnection()
        assert not transport.connected
        assert b"\x88\x02\x03\xe8" == transport.value()
        # We can call loseConnection again without side effects
        webSocketsTranport.loseConnection()

    def test_loseConnectionCodeAndReason(self):
        """
        L{WebSocketsTransport.loseConnection} accepts a code and a reason which
        are used to build the closing frame.
        """
        transport = StringTransportWithDisconnection()
        transport.protocol = Protocol()
        webSocketsTranport = WebSocketsTransport(transport)
        webSocketsTranport.loseConnection(STATUSES.GOING_AWAY, b"Going away")
        assert b"\x88\x0c\x03\xe9Going away" == transport.value()


class TestWebSocketsProtocolWrapper:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.accumulatingProtocol = AccumulatingProtocol()
        self.protocol = WebSocketsProtocolWrapper(self.accumulatingProtocol)
        self.transport = StringTransportWithDisconnection()
        self.protocol.makeConnection(self.transport)
        self.transport.protocol = self.protocol

    def test_dataReceived(self):
        """
        L{WebSocketsProtocolWrapper.dataReceived} forwards frame content to the
        underlying protocol.
        """
        self.protocol.dataReceived(
            _makeFrame(b"Hello", CONTROLS.TEXT, True, mask=b"abcd")
        )
        assert b"Hello" == self.accumulatingProtocol.data

    def test_controlFrames(self):
        """
        L{WebSocketsProtocolWrapper} doesn't forward data from control frames
        to the underlying protocol.
        """
        self.protocol.dataReceived(
            _makeFrame(b"Hello", CONTROLS.PING, True, mask=b"abcd")
        )
        self.protocol.dataReceived(
            _makeFrame(b"Hello", CONTROLS.PONG, True, mask=b"abcd")
        )
        self.protocol.dataReceived(
            _makeFrame(b"", CONTROLS.CLOSE, True, mask=b"abcd")
        )
        assert b"" == self.accumulatingProtocol.data

    def test_loseConnection(self):
        """
        L{WebSocketsProtocolWrapper.loseConnection} sends a close frame and
        disconnects the transport.
        """
        self.protocol.loseConnection()
        assert not self.transport.connected
        assert b"\x88\x02\x03\xe8" == self.transport.value()

    def test_write(self):
        """
        L{WebSocketsProtocolWrapper.write} creates and writes a frame from the
        payload passed.
        """
        self.accumulatingProtocol.transport.write(b"Hello")
        assert b"\x81\x05Hello" == self.transport.value()

    def test_writeSequence(self):
        """
        L{WebSocketsProtocolWrapper.writeSequence} writes a frame for every
        chunk passed.
        """
        self.accumulatingProtocol.transport.writeSequence([b"Hello", b"World"])
        assert b"\x81\x05Hello\x81\x05World" == self.transport.value()

    def test_getHost(self):
        """
        L{WebSocketsProtocolWrapper.getHost} returns the transport C{getHost}.
        """
        assert (
            self.transport.getHost()
            == self.accumulatingProtocol.transport.getHost()
        )

    def test_getPeer(self):
        """
        L{WebSocketsProtocolWrapper.getPeer} returns the transport C{getPeer}.
        """
        assert (
            self.transport.getPeer()
            == self.accumulatingProtocol.transport.getPeer()
        )

    def test_connectionLost(self):
        """
        L{WebSocketsProtocolWrapper.connectionLost} forwards the connection
        lost call to the underlying protocol.
        """
        self.transport.loseConnection()
        assert self.accumulatingProtocol.closed


class TestWebSocketsResource:
    @pytest.fixture(autouse=True)
    def _setup(self):
        class SavingEchoFactory(Factory):
            def buildProtocol(oself, addr):
                return self.echoProtocol

        factory = SavingEchoFactory()
        self.echoProtocol = WebSocketsProtocol(SavingEchoReceiver())

        self.resource = WebSocketsResource(lookupProtocolForFactory(factory))

    def assertRequestFail(self, request):
        """
        Helper method checking that the provided C{request} fails with a I{400}
        request code, without data or headers.

        @param request: The request to render.
        @type request: L{DummyRequest}
        """
        result = self.resource.render(request)
        assert b"" == result
        assert {} == {
            name: value
            for name, value in request.responseHeaders.getAllRawHeaders()
        }
        assert [] == request.written
        assert 400 == request.responseCode

    def update_headers(self, request, headers):
        for name, value in headers.items():
            request.requestHeaders.addRawHeader(name=name, value=value)

    def test_getChildWithDefault(self):
        """
        L{WebSocketsResource.getChildWithDefault} raises a C{RuntimeError} when
        called.
        """
        with pytest.raises(RuntimeError):
            self.resource.getChildWithDefault(
                b"foo",
                DummyRequest(b"/"),
            )

    def test_putChild(self):
        """
        L{WebSocketsResource.putChild} raises C{RuntimeError} when called.
        """
        with pytest.raises(RuntimeError):
            self.resource.putChild(b"foo", Resource())

    def test_IResource(self):
        """
        L{WebSocketsResource} implements L{IResource}.
        """
        assert verifyObject(IResource, self.resource)

    def test_render(self):
        """
        When rendering a request, L{WebSocketsResource} uses the
        C{Sec-WebSocket-Key} header to generate a C{Sec-WebSocket-Accept}
        value. It creates a L{WebSocketsProtocol} instance connected to the
        protocol provided by the user factory.
        """
        request = DummyRequest(b"/")
        request.requestHeaders = Headers(
            {b"user-agent": [b"user-agent"], b"host": [b"host"]}
        )
        transport = StringTransportWithDisconnection()
        transport.protocol = Protocol()
        request.transport = transport
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        result = self.resource.render(request)
        assert NOT_DONE_YET == result
        assert {
            b"Connection": [b"Upgrade"],
            b"Upgrade": [b"WebSocket"],
            b"Sec-Websocket-Accept": [b"oYBv54i42V5dw6KnZqOFroecUTc="],
        } == {
            name: value
            for name, value in request.responseHeaders.getAllRawHeaders()
        }
        assert [b""] == request.written
        assert 101 == request.responseCode
        assert request.transport is None
        assert isinstance(transport.protocol._receiver, SavingEchoReceiver)
        assert request.getHeader(b"cookie") == transport.cookies
        assert request.uri == transport.uri

    def test_renderProtocol(self):
        """
        If protocols are specified via the C{Sec-WebSocket-Protocol} header,
        L{WebSocketsResource} passes them to its C{lookupProtocol} argument,
        which can decide which protocol to return, and which is accepted.
        """

        def lookupProtocol(names, otherRequest):
            assert [b"foo", b"bar"] == names
            assert request is otherRequest
            return self.echoProtocol, b"bar"

        self.resource = WebSocketsResource(lookupProtocol)

        request = DummyRequest(b"/")
        request.requestHeaders = Headers(
            {
                b"sec-websocket-protocol": [b"foo", b"bar"],
                b"user-agent": [b"user-agent"],
                b"host": [b"host"],
            }
        )
        transport = StringTransportWithDisconnection()
        transport.protocol = Protocol()
        request.transport = transport
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        result = self.resource.render(request)
        assert NOT_DONE_YET == result
        assert {
            b"Connection": [b"Upgrade"],
            b"Upgrade": [b"WebSocket"],
            b"Sec-Websocket-Protocol": [b"bar"],
            b"Sec-Websocket-Accept": [b"oYBv54i42V5dw6KnZqOFroecUTc="],
        } == {
            name: value
            for name, value in request.responseHeaders.getAllRawHeaders()
        }
        assert [b""] == request.written
        assert 101 == request.responseCode

    def test_renderWrongUpgrade(self):
        """
        If the C{Upgrade} header contains an invalid value,
        L{WebSocketsResource} returns a failed request.
        """
        request = DummyRequest(b"/")
        self.update_headers(
            request,
            headers={
                b"upgrade": b"wrong",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        self.assertRequestFail(request)

    def test_renderNoUpgrade(self):
        """
        If the C{Upgrade} header is not set, L{WebSocketsResource} returns a
        failed request.
        """
        request = DummyRequest(b"/")
        self.update_headers(
            request,
            headers={
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        self.assertRequestFail(request)

    def test_renderPOST(self):
        """
        If the method is not C{GET}, L{WebSocketsResource} returns a failed
        request.
        """
        request = DummyRequest(b"/")
        request.method = b"POST"
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        self.assertRequestFail(request)

    def test_renderWrongConnection(self):
        """
        If the C{Connection} header contains an invalid value,
        L{WebSocketsResource} returns a failed request.
        """
        request = DummyRequest(b"/")
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Wrong",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        self.assertRequestFail(request)

    def test_renderNoConnection(self):
        """
        If the C{Connection} header is not set, L{WebSocketsResource} returns a
        failed request.
        """
        request = DummyRequest(b"/")
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        self.assertRequestFail(request)

    def test_renderNoKey(self):
        """
        If the C{Sec-WebSocket-Key} header is not set, L{WebSocketsResource}
        returns a failed request.
        """
        request = DummyRequest(b"/")
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-version": b"13",
            },
        )
        self.assertRequestFail(request)

    def test_renderWrongVersion(self):
        """
        If the value of the C{Sec-WebSocket-Version} is not 13,
        L{WebSocketsResource} returns a failed request.
        """
        request = DummyRequest(b"/")

        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"11",
            },
        )
        result = self.resource.render(request)
        assert b"" == result
        assert ["13"] == request.responseHeaders.getRawHeaders(
            "sec-websocket-version"
        )
        assert [] == request.written
        assert 400 == request.responseCode

    def test_renderNoProtocol(self):
        """
        If the underlying factory doesn't return any protocol,
        L{WebSocketsResource} returns a failed request with a C{502} code.
        """
        request = DummyRequest(b"/")
        request.requestHeaders = Headers(
            {b"user-agent": [b"user-agent"], b"host": [b"host"]}
        )
        request.transport = StringTransportWithDisconnection()
        self.echoProtocol = None
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        result = self.resource.render(request)
        assert b"" == result
        assert {} == {
            name: value
            for name, value in request.responseHeaders.getAllRawHeaders()
        }
        assert [] == request.written
        assert 502 == request.responseCode

    def test_renderSecureRequest(self):
        """
        When the rendered request is over HTTPS, L{WebSocketsResource} wraps
        the protocol of the C{TLSMemoryBIOProtocol} instance.
        """
        request = DummyRequest(b"/")
        request.requestHeaders = Headers(
            {b"user-agent": [b"user-agent"], b"host": [b"host"]}
        )
        transport = StringTransportWithDisconnection()
        secureProtocol = TLSMemoryBIOProtocol(Factory(), Protocol())
        transport.protocol = secureProtocol
        request.transport = transport
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        result = self.resource.render(request)
        assert NOT_DONE_YET == result
        assert {
            b"Connection": [b"Upgrade"],
            b"Upgrade": [b"WebSocket"],
            b"Sec-Websocket-Accept": [b"oYBv54i42V5dw6KnZqOFroecUTc="],
        } == {
            name: value
            for name, value in request.responseHeaders.getAllRawHeaders()
        }
        assert [b""] == request.written
        assert 101 == request.responseCode
        assert request.transport is None
        assert isinstance(
            transport.protocol.wrappedProtocol, WebSocketsProtocol
        )
        assert isinstance(
            transport.protocol.wrappedProtocol._receiver, SavingEchoReceiver
        )

    def test_renderRealRequest(self):
        """
        The request managed by L{WebSocketsResource.render} doesn't contain
        unnecessary HTTP headers like I{Content-Type}.
        """
        channel = DummyChannel()
        channel.transport = StringTransportWithDisconnection()
        channel.transport.protocol = channel
        request = Request(channel, False)
        headers = {
            b"upgrade": b"Websocket",
            b"connection": b"Upgrade",
            b"sec-websocket-key": b"secure",
            b"sec-websocket-version": b"13",
            b"user-agent": b"user-agent",
            b"client": b"client",
            b"host": b"host",
        }
        for key, value in headers.items():
            request.requestHeaders.setRawHeaders(key, [value])
        request.method = b"GET"
        request.clientproto = b"HTTP/1.1"
        request.client = IPv6Address("TCP", "fe80::1", "80")
        result = self.resource.render(request)
        assert NOT_DONE_YET == result
        assert sorted(
            [
                (b"Connection", [b"Upgrade"]),
                (b"Sec-Websocket-Accept", [b"oYBv54i42V5dw6KnZqOFroecUTc="]),
                (b"Upgrade", [b"WebSocket"]),
                (b"Transfer-Encoding", [b"chunked"]),
            ]
        ) == sorted(
            request.responseHeaders.getAllRawHeaders(),
        )
        assert channel.transport.value().startswith(
            b"HTTP/1.1 101 Switching Protocols\r\n"
        )
        assert 101 == request.code
        assert request.transport is None

    def test_renderIProtocol(self):
        """
        If the protocol returned by C{lookupProtocol} isn't a
        C{WebSocketsProtocol}, L{WebSocketsResource} wraps it automatically
        with L{WebSocketsProtocolWrapper}.
        """

        def lookupProtocol(names, otherRequest):
            return AccumulatingProtocol(), None

        self.resource = WebSocketsResource(lookupProtocol)

        request = DummyRequest(b"/")
        request.requestHeaders = Headers(
            {b"user-agent": [b"user-agent"], b"host": [b"host"]}
        )
        transport = StringTransportWithDisconnection()
        transport.protocol = Protocol()
        request.transport = transport
        self.update_headers(
            request,
            headers={
                b"upgrade": b"Websocket",
                b"connection": b"Upgrade",
                b"sec-websocket-key": b"secure",
                b"sec-websocket-version": b"13",
            },
        )
        result = self.resource.render(request)
        assert NOT_DONE_YET == result
        assert isinstance(transport.protocol, WebSocketsProtocolWrapper)
        assert isinstance(
            transport.protocol.wrappedProtocol, AccumulatingProtocol
        )
