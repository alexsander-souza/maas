# provisioningserver Subsystem

## Purpose

Legacy Python-based rack controller providing network services (DHCP, DNS, PXE), power management, and image distribution for MAAS. This subsystem is in maintenance mode and being gradually replaced by the modern Go-based maasagent.

**Status**: Maintenance mode - being replaced by maasagent.

## Location

`src/provisioningserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Twisted**: Asynchronous event-driven framework
- **tftp**: TFTP server for PXE boot
- **ISC DHCP**: DHCP server integration
- **BIND**: DNS server integration

### Key Libraries
- **twisted**: Core async framework
- **netaddr**: Network address manipulation
- **pyroute2**: Network interface management
- **python-apt**: Package management integration
- **simplestreams**: Image synchronization

## Architectural Constraints

### Twisted Event Loop

Built on Twisted's asynchronous event-driven architecture:
- Reactor pattern for event handling
- Deferred-based async operations
- Protocol implementations for network services
- Legacy async model (pre-async/await)

### Service-Oriented Architecture

Multiple independent services running in single process:
- **DHCP Service**: Dynamic host configuration
- **DNS Service**: Domain name resolution
- **TFTP Service**: Boot file serving
- **HTTP Service**: Image downloads
- **RPC Service**: Region communication

### Legacy Codebase

Written before modern Python async:
- Uses Twisted Deferreds instead of async/await
- Complex callback chains
- Event-driven patterns
- Being gradually deprecated

## Key Patterns

> **See**: [python-patterns.md](../../skills/languages/python-patterns.md) for common Python patterns.

### Twisted Service Pattern

Services implement Twisted's IService interface:

```python
from twisted.application import service
from twisted.internet import defer

class DHCPService(service.Service):
    """DHCP service for rack controller."""
    
    def __init__(self, interface):
        self.interface = interface
        self.dhcp_server = None
    
    def startService(self):
        """Start DHCP service."""
        service.Service.startService(self)
        self.dhcp_server = DHCPServer(self.interface)
        return self.dhcp_server.start()
    
    def stopService(self):
        """Stop DHCP service gracefully."""
        if self.dhcp_server:
            return self.dhcp_server.stop()
        return defer.succeed(None)
```

### Deferred Pattern

Twisted uses Deferreds for async operations:

```python
from twisted.internet import defer

@defer.inlineCallbacks
def configure_interface(interface_name, ip_address):
    """Configure network interface asynchronously."""
    # Yield Deferred to wait for result
    result = yield check_interface_exists(interface_name)
    if not result:
        raise InterfaceNotFoundError(interface_name)
    
    yield set_interface_ip(interface_name, ip_address)
    yield bring_interface_up(interface_name)
    
    defer.returnValue(True)

# Modern equivalent with async/await:
# async def configure_interface(interface_name, ip_address):
#     result = await check_interface_exists(interface_name)
#     ...
```

### RPC Client Pattern

Communication with region controller:

```python
from provisioningserver.rpc.region import getRegionClient

@defer.inlineCallbacks
def report_machine_status(system_id, status):
    """Report machine status to region."""
    client = getRegionClient()
    
    try:
        response = yield client(
            ReportMachineStatus,
            system_id=system_id,
            status=status
        )
        defer.returnValue(response)
    except Exception as e:
        log.error(f"Failed to report status: {e}")
        raise
```

### Power Control Pattern

Abstract power management:

```python
from provisioningserver.drivers.power import PowerDriver

class IPMIPowerDriver(PowerDriver):
    """IPMI power control driver."""
    
    name = "ipmi"
    description = "IPMI power control"
    settings = [
        {"name": "power_address", "label": "IP Address"},
        {"name": "power_user", "label": "Username"},
        {"name": "power_pass", "label": "Password", "secret": True},
    ]
    
    @defer.inlineCallbacks
    def power_on(self, system_id, context):
        """Power on machine via IPMI."""
        command = [
            "ipmitool",
            "-I", "lanplus",
            "-H", context["power_address"],
            "-U", context["power_user"],
            "-P", context["power_pass"],
            "power", "on"
        ]
        
        result = yield run_command(command)
        defer.returnValue(result.returncode == 0)
    
    @defer.inlineCallbacks
    def power_off(self, system_id, context):
        """Power off machine via IPMI."""
        command = [
            "ipmitool",
            "-I", "lanplus",
            "-H", context["power_address"],
            "-U", context["power_user"],
            "-P", context["power_pass"],
            "power", "off"
        ]
        
        result = yield run_command(command)
        defer.returnValue(result.returncode == 0)
```

### Image Management Pattern

Synchronize and serve boot images:

```python
from provisioningserver.import_images import download_images

@defer.inlineCallbacks
def sync_boot_images(source_url):
    """Synchronize boot images from source."""
    log.info(f"Syncing images from {source_url}")
    
    # Download image metadata
    metadata = yield download_image_metadata(source_url)
    
    # Download each image
    for image in metadata.images:
        if not image_exists_locally(image):
            log.info(f"Downloading {image.name}")
            yield download_image(image)
    
    # Update TFTP configuration
    yield update_tftp_config()
    
    defer.returnValue(len(metadata.images))
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) and [python-testing.md](../../skills/languages/python-testing.md)

### Twisted Trial Tests

Use Twisted's test framework:

```python
from twisted.trial import unittest
from twisted.internet import defer

class TestDHCPService(unittest.TestCase):
    """Tests for DHCP service."""
    
    @defer.inlineCallbacks
    def test_start_service(self):
        """Test starting DHCP service."""
        service = DHCPService("eth0")
        yield service.startService()
        
        self.assertTrue(service.running)
        self.assertIsNotNone(service.dhcp_server)
        
        yield service.stopService()
    
    @defer.inlineCallbacks
    def test_create_lease(self):
        """Test creating DHCP lease."""
        service = DHCPService("eth0")
        yield service.startService()
        
        lease = yield service.create_lease(
            mac="00:11:22:33:44:55",
            ip="192.168.1.100"
        )
        
        self.assertEqual(lease.mac, "00:11:22:33:44:55")
        self.assertEqual(lease.ip, "192.168.1.100")
        
        yield service.stopService()
```

### Mock RPC Calls

Mock region communication:

```python
from unittest import mock

class TestRPCClient(unittest.TestCase):
    """Test RPC communication."""
    
    @defer.inlineCallbacks
    def test_report_status(self):
        """Test reporting status to region."""
        with mock.patch('provisioningserver.rpc.region.getRegionClient') as mock_client:
            mock_response = defer.succeed({"status": "ok"})
            mock_client.return_value.return_value = mock_response
            
            result = yield report_machine_status("abc123", "deployed")
            
            self.assertEqual(result["status"], "ok")
            mock_client.return_value.assert_called_once()
```

### Running Tests

```bash
# Run with Twisted trial
trial provisioningserver.tests

# Run specific test module
trial provisioningserver.tests.test_dhcp

# Run with coverage
coverage run --source=provisioningserver -m trial provisioningserver.tests
coverage report
```

## Development Guidelines

### Working with Deferreds

Understanding Twisted's async model:

```python
from twisted.internet import defer

# Basic Deferred usage
def async_operation():
    d = defer.Deferred()
    
    def callback_success(result):
        # Process successful result
        return result * 2
    
    def callback_error(failure):
        # Handle error
        log.error(f"Operation failed: {failure}")
        return None
    
    d.addCallback(callback_success)
    d.addErrback(callback_error)
    
    return d

# Using inlineCallbacks (recommended)
@defer.inlineCallbacks
def process_data(data):
    """Process data with multiple async steps."""
    validated = yield validate_data(data)
    transformed = yield transform_data(validated)
    result = yield save_data(transformed)
    defer.returnValue(result)
```

### Service Lifecycle

Proper service management:

```python
from twisted.application import service

class MyService(service.Service):
    """Custom service implementation."""
    
    def startService(self):
        """Initialize and start service."""
        service.Service.startService(self)
        # Initialize resources
        self.connection = establish_connection()
        self.timer = task.LoopingCall(self.periodic_task)
        self.timer.start(60.0)  # Run every 60 seconds
    
    def stopService(self):
        """Clean up and stop service."""
        # Stop periodic tasks
        if self.timer.running:
            self.timer.stop()
        
        # Close connections
        if self.connection:
            self.connection.close()
        
        return service.Service.stopService(self)
    
    def periodic_task(self):
        """Task run periodically."""
        # Perform periodic work
        pass
```

### Error Handling in Twisted

Handle failures properly:

```python
from twisted.python import log, failure

@defer.inlineCallbacks
def risky_operation(data):
    """Operation that might fail."""
    try:
        result = yield perform_operation(data)
        defer.returnValue(result)
    except ValueError as e:
        log.error(f"Validation error: {e}")
        raise
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        raise OperationError(f"Failed to process: {e}")
```

## Integration Points

### MAAS Region Controller
- RPC communication for commands and status
- Report machine discoveries and commissioning results
- Receive deployment instructions
- See [maasserver.md](./maasserver.md)

### ISC DHCP Server
- Generate DHCP configuration files
- Manage leases and reservations
- Dynamic DNS updates

### BIND DNS Server
- Generate zone files
- Manage forward and reverse zones
- Dynamic DNS updates

### TFTP Server
- Serve PXE boot files
- Provide bootloader configurations
- Support multiple architectures

### HTTP Server
- Serve OS images
- Provide cloud-init configurations
- Curtin installation scripts

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Blocking the Reactor

❌ **Don't** block the Twisted reactor:
```python
@defer.inlineCallbacks
def bad_function():
    time.sleep(10)  # WRONG! Blocks reactor
    result = yield some_operation()
```

✅ **Do** use reactor.callLater for delays:
```python
from twisted.internet import reactor, defer

@defer.inlineCallbacks
def good_function():
    d = defer.Deferred()
    reactor.callLater(10, d.callback, None)  # Non-blocking delay
    yield d
    result = yield some_operation()
```

### Unhandled Deferreds

❌ **Don't** ignore Deferred results:
```python
def bad_function():
    d = async_operation()  # WRONG! Deferred not handled
    return "done"
```

✅ **Do** return or yield Deferreds:
```python
@defer.inlineCallbacks
def good_function():
    result = yield async_operation()  # Properly handled
    defer.returnValue(result)
```

### Missing Error Handlers

❌ **Don't** forget errbacks:
```python
d = risky_operation()
d.addCallback(handle_success)  # WRONG! No error handler
```

✅ **Do** add errbacks:
```python
d = risky_operation()
d.addCallback(handle_success)
d.addErrback(handle_error)  # Proper error handling
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### Power Credentials
- Store power control credentials securely
- Never log passwords
- Use secrets management for sensitive data

### Network Services
- Restrict DHCP to management networks
- Validate DNS queries to prevent abuse
- Secure TFTP access to authorized clients

### RPC Communication
- Use TLS for region communication
- Validate RPC messages
- Authenticate rack controllers

## Performance Considerations

### Reactor Performance
- Keep callback chains short
- Avoid blocking operations
- Use thread pools for CPU-intensive work

### Network Services
- Configure appropriate buffer sizes
- Use connection pooling
- Optimize DHCP response times

### Image Management
- Use efficient image compression
- Implement caching for frequently accessed images
- Parallel image downloads where possible

## Migration to maasagent

This subsystem is being replaced by maasagent:
- **New deployments**: Use maasagent
- **Existing deployments**: Gradual migration path
- **Feature freeze**: No new features in provisioningserver
- **Bug fixes only**: Maintenance mode

See [maasagent.md](./maasagent.md) for the replacement architecture.

## Additional Resources

- **Twisted Documentation**: https://docs.twistedmatrix.com/
- **Twisted Tutorial**: https://docs.twistedmatrix.com/en/stable/core/howto/async.html
- **ISC DHCP**: https://www.isc.org/dhcp/
- **BIND DNS**: https://www.isc.org/bind/
- **Related**: [python-patterns.md](../../skills/languages/python-patterns.md), [maasagent.md](./maasagent.md)