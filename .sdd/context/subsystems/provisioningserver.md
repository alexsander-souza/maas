# provisioningserver Subsystem

## Purpose

Rack controller provisioning services that manage the provisioning and deployment of machines in MAAS. This subsystem runs on rack controllers and handles power management, network boot services (TFTP/HTTP), image downloads, and communication with region controllers.

**Status**: Active - core infrastructure component for rack controllers.

## Location

`src/provisioningserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Twisted**: Asynchronous networking framework
- **RPC**: Custom RPC protocol for region-rack communication

### Key Libraries
- **twisted**: Event-driven networking engine
- **tftp**: TFTP server implementation
- **pexpect**: Power driver automation
- **requests**: HTTP client for image downloads
- **netifaces**: Network interface detection

## Architectural Constraints

### Rack Controller Architecture

The provisioning server runs on rack controllers, which are distributed nodes that manage provisioning in specific network segments:

```
┌─────────────────────────────────┐
│   Region Controller             │
│   - Database                    │
│   - API                         │
│   - Web UI                      │
└────────────┬────────────────────┘
             │ RPC
             │
      ┌──────┴──────┬──────────────┐
      │             │              │
┌─────▼──────┐ ┌────▼──────┐ ┌────▼──────┐
│ Rack 1     │ │ Rack 2    │ │ Rack 3    │
│ - DHCP     │ │ - DHCP    │ │ - DHCP    │
│ - TFTP     │ │ - TFTP    │ │ - TFTP    │
│ - HTTP     │ │ - HTTP    │ │ - HTTP    │
│ - Power    │ │ - Power   │ │ - Power   │
└────────────┘ └───────────┘ └───────────┘
```

### Twisted Async Model

Uses Twisted's deferred-based asynchronous programming model (not modern async/await):

- Deferred chains for async operations
- Reactor pattern for event loop
- Thread pool for blocking operations
- Protocol implementations for network services

### Stateless Operation

Rack controllers maintain minimal state:
- Configuration pulled from region controller
- Images cached locally
- No persistent database
- Restartable without data loss

## Key Patterns

### Twisted Deferred Pattern

Use Twisted deferreds for asynchronous operations:

```python
from twisted.internet import defer
from twisted.internet.threads import deferToThread

@defer.inlineCallbacks
def provision_machine(system_id):
    """Provision a machine using Twisted deferreds."""
    # Power on the machine
    yield deferToThread(power_on, system_id)
    
    # Wait for network boot
    boot_result = yield wait_for_network_boot(system_id)
    
    # Configure deployment
    config = yield get_deployment_config(system_id)
    
    defer.returnValue(config)

def power_on(system_id):
    """Blocking power operation - run in thread."""
    driver = get_power_driver(system_id)
    driver.power_on()
```

### Power Driver Pattern

Power drivers implement a common interface for controlling machine power:

```python
from provisioningserver.drivers import PowerDriver

class IPMIPowerDriver(PowerDriver):
    """IPMI power driver implementation."""
    
    name = "ipmi"
    description = "IPMI power driver"
    settings = [
        {
            "name": "power_address",
            "label": "IP Address",
            "required": True,
        },
        {
            "name": "power_user",
            "label": "Username",
            "required": True,
        },
        {
            "name": "power_pass",
            "label": "Password",
            "required": True,
            "secret": True,
        },
    ]
    
    def power_on(self, system_id, context):
        """Power on the machine via IPMI."""
        command = [
            "ipmitool",
            "-I", "lanplus",
            "-H", context["power_address"],
            "-U", context["power_user"],
            "-P", context["power_pass"],
            "power", "on"
        ]
        return self._run_command(command)
    
    def power_off(self, system_id, context):
        """Power off the machine via IPMI."""
        command = [
            "ipmitool",
            "-I", "lanplus",
            "-H", context["power_address"],
            "-U", context["power_user"],
            "-P", context["power_pass"],
            "power", "off"
        ]
        return self._run_command(command)
    
    def power_query(self, system_id, context):
        """Query power state via IPMI."""
        command = [
            "ipmitool",
            "-I", "lanplus",
            "-H", context["power_address"],
            "-U", context["power_user"],
            "-P", context["power_pass"],
            "power", "status"
        ]
        output = self._run_command(command)
        return "on" if "on" in output.lower() else "off"
```

### TFTP Service Pattern

TFTP server for network boot:

```python
from twisted.internet import reactor, defer
from provisioningserver.boot import BootMethodRegister

class TFTPBackend:
    """TFTP backend for serving boot files."""
    
    def __init__(self, base_path, client_service):
        self.base_path = base_path
        self.client_service = client_service
    
    @defer.inlineCallbacks
    def get_reader(self, file_name, peer):
        """Get file reader for TFTP request."""
        # Log request
        yield self._log_request(file_name, peer)
        
        # Check if this is a boot request
        boot_method = BootMethodRegister.get_by_name(file_name)
        if boot_method:
            # Generate boot configuration dynamically
            config = yield self._get_boot_config(boot_method, peer)
            defer.returnValue(StringReader(config))
        
        # Serve static file
        file_path = os.path.join(self.base_path, file_name)
        if os.path.exists(file_path):
            defer.returnValue(open(file_path, "rb"))
        
        # File not found
        raise FileNotFoundError(file_name)
```

### RPC Communication Pattern

Communication with region controller via RPC:

```python
from provisioningserver.rpc.region import (
    GetBootConfig,
    MarkNodeFailed,
)

@defer.inlineCallbacks
def get_boot_config_from_region(system_id, arch, subarch):
    """Get boot configuration from region controller."""
    client = yield getRegionClient()
    
    result = yield client.call(
        GetBootConfig,
        system_id=system_id,
        local_ip=get_local_ip(),
        remote_ip=get_remote_ip(),
        arch=arch,
        subarch=subarch,
    )
    
    defer.returnValue(result)

@defer.inlineCallbacks
def report_boot_failure(system_id, error_message):
    """Report boot failure to region controller."""
    client = yield getRegionClient()
    
    yield client.call(
        MarkNodeFailed,
        system_id=system_id,
        error_message=error_message,
    )
```

### HTTP Boot Service Pattern

HTTP server for serving boot images and configuration:

```python
from twisted.web import server, resource
from twisted.internet import reactor

class BootImageResource(resource.Resource):
    """HTTP resource for serving boot images."""
    
    isLeaf = True
    
    def __init__(self, image_store):
        resource.Resource.__init__(self)
        self.image_store = image_store
    
    def render_GET(self, request):
        """Serve boot image via HTTP."""
        system_id = request.args.get(b"system_id", [None])[0]
        arch = request.args.get(b"arch", [None])[0]
        
        if not system_id or not arch:
            request.setResponseCode(400)
            return b"Missing required parameters"
        
        # Get image path
        image_path = self.image_store.get_image_path(arch)
        
        if not os.path.exists(image_path):
            request.setResponseCode(404)
            return b"Image not found"
        
        # Serve file
        request.setHeader(b"content-type", b"application/octet-stream")
        with open(image_path, "rb") as f:
            return f.read()
```

## Testing Requirements

### Test Framework

Use Twisted's trial test runner and testtools:

```python
from twisted.trial import unittest
from twisted.internet import defer
from provisioningserver.power import PowerDriver

class TestIPMIPowerDriver(unittest.TestCase):
    """Test IPMI power driver."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.driver = IPMIPowerDriver()
        self.context = {
            "power_address": "192.168.1.100",
            "power_user": "admin",
            "power_pass": "password",
        }
    
    @defer.inlineCallbacks
    def test_power_on(self):
        """Test powering on a machine."""
        result = yield self.driver.power_on("test-system", self.context)
        self.assertIsNotNone(result)
    
    def test_validate_context(self):
        """Test context validation."""
        # Valid context
        self.driver.validate_context(self.context)
        
        # Invalid context - missing required field
        invalid_context = {"power_address": "192.168.1.100"}
        with self.assertRaises(ValueError):
            self.driver.validate_context(invalid_context)
```

### Mock RPC Calls

Mock region controller RPC calls in tests:

```python
from twisted.internet import defer
from unittest.mock import Mock, patch

class TestBootService(unittest.TestCase):
    """Test boot service."""
    
    @defer.inlineCallbacks
    def test_get_boot_config(self):
        """Test getting boot configuration."""
        mock_client = Mock()
        mock_client.call = Mock(return_value=defer.succeed({
            "kernel": "/boot/vmlinuz",
            "initrd": "/boot/initrd",
            "cmdline": "root=/dev/sda1",
        }))
        
        with patch("provisioningserver.boot.getRegionClient",
                   return_value=defer.succeed(mock_client)):
            config = yield get_boot_config("test-system")
            
            self.assertEqual(config["kernel"], "/boot/vmlinuz")
            mock_client.call.assert_called_once()
```

### Testing Async Operations

Use inlineCallbacks for testing async code:

```python
class TestAsyncOperations(unittest.TestCase):
    """Test async operations."""
    
    @defer.inlineCallbacks
    def test_deferred_chain(self):
        """Test deferred chain execution."""
        results = []
        
        @defer.inlineCallbacks
        def async_operation(value):
            yield defer.succeed(None)  # Simulate async work
            results.append(value)
            defer.returnValue(value * 2)
        
        result = yield async_operation(5)
        
        self.assertEqual(result, 10)
        self.assertEqual(results, [5])
```

### Running Tests

```bash
# Run all provisioning server tests
trial provisioningserver

# Run specific test module
trial provisioningserver.tests.test_power

# Run with coverage
coverage run --source=provisioningserver -m twisted.trial provisioningserver
coverage report
```

## Development Guidelines

### Reactor Usage

**Critical**: Be extremely careful with the Twisted reactor:

- Only one reactor per process
- Never call `reactor.run()` in library code
- Use `reactor.callLater()` for delayed operations
- Clean up with `reactor.stop()` when appropriate

```python
from twisted.internet import reactor

# ✅ Good: Schedule delayed operation
def delayed_operation():
    reactor.callLater(5.0, do_something)

# ❌ Bad: Don't run reactor in library code
def bad_example():
    reactor.run()  # WRONG! Blocks forever
```

### Thread Pool for Blocking Operations

Use `deferToThread` for blocking I/O:

```python
from twisted.internet.threads import deferToThread

@defer.inlineCallbacks
def good_example():
    """Run blocking operation in thread pool."""
    # Blocking operation runs in thread
    result = yield deferToThread(blocking_io_operation)
    defer.returnValue(result)

def blocking_io_operation():
    """Blocking operation that would block reactor."""
    with open("/etc/config", "r") as f:
        return f.read()
```

### Error Handling in Deferreds

Proper error handling in deferred chains:

```python
@defer.inlineCallbacks
def operation_with_error_handling():
    """Handle errors in deferred chain."""
    try:
        result = yield risky_operation()
        defer.returnValue(result)
    except SpecificError as e:
        log.error("Operation failed: %s", e)
        # Return default or re-raise
        defer.returnValue(None)
    except Exception as e:
        log.error("Unexpected error: %s", e)
        raise
```

### Adding New Power Drivers

1. Create driver class extending `PowerDriver`
2. Define settings schema
3. Implement `power_on`, `power_off`, `power_query`
4. Register driver in `PowerDriverRegistry`
5. Write tests with mocked commands
6. Document driver in user docs

## Integration Points

### Region Controller

Communicates with region controller via RPC:
- Boot configuration requests
- Machine status updates
- Event logging
- Image synchronization

### MAAS Agent

Future integration with new Go-based agent:
- DHCP service coordination
- DNS service coordination
- Metrics collection

### Network Services

Provides network boot services:
- DHCP server
- TFTP server
- HTTP server for images
- Proxy service

### Power Management

Interfaces with BMC/IPMI systems:
- IPMI
- Redfish
- Virsh (libvirt)
- AWS, Azure, GCP APIs
- Custom power drivers

## Common Pitfalls

### Blocking the Reactor

❌ **Don't**:
```python
def bad_power_query():
    # Blocking I/O on reactor thread - WRONG!
    output = subprocess.check_output(["ipmitool", "..."])
    return output
```

✅ **Do**:
```python
@defer.inlineCallbacks
def good_power_query():
    # Run in thread pool
    output = yield deferToThread(
        subprocess.check_output, ["ipmitool", "..."]
    )
    defer.returnValue(output)
```

### Deferred Return Values

❌ **Don't**:
```python
@defer.inlineCallbacks
def bad_example():
    result = yield some_operation()
    return result  # WRONG! Use defer.returnValue()
```

✅ **Do**:
```python
@defer.inlineCallbacks
def good_example():
    result = yield some_operation()
    defer.returnValue(result)  # Correct
```

### Error Propagation

❌ **Don't**:
```python
def bad_error_handling(deferred):
    deferred.addCallback(lambda x: x * 2)
    # Error silently ignored
```

✅ **Do**:
```python
def good_error_handling(deferred):
    deferred.addCallback(lambda x: x * 2)
    deferred.addErrback(log_error)  # Handle errors
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Twisted Async**: Deferred-based async programming
- **Python Development**: General Python patterns
- **Network Programming**: TCP/IP, DHCP, TFTP, HTTP
- **Power Management**: BMC/IPMI protocols
- **RPC**: Remote procedure call patterns
- **Testing**: Async test patterns with trial

## Security Considerations

### Power Credentials

Secure handling of power credentials:
- Never log passwords
- Encrypt credentials at rest
- Use secure channels for transmission
- Validate credential format

### Network Services

Secure network service configuration:
- Restrict TFTP/HTTP to trusted networks
- Validate all file requests
- Prevent directory traversal
- Rate limiting for DoS prevention

### RPC Security

Secure region-rack communication:
- TLS for RPC connections
- Certificate validation
- Authentication tokens
- Authorization checks

## Performance Considerations

### Async I/O

Maximize async operations:
- Non-blocking network I/O
- Thread pool for blocking ops
- Efficient event loop usage

### Connection Pooling

Reuse connections where possible:
- HTTP client connection pooling
- RPC connection reuse
- Database connection pooling

### Caching

Cache frequently accessed data:
- Boot images cached locally
- Configuration cached with TTL
- DNS resolution caching

## Documentation

### Power Driver Documentation

Document each power driver:
- Supported hardware
- Required settings
- Setup instructions
- Troubleshooting guide

### RPC Protocol

Document RPC methods:
- Method signatures
- Parameter descriptions
- Return values
- Error conditions

### Network Services

Document network service configuration:
- DHCP configuration
- TFTP setup
- HTTP endpoints
- Port requirements

## Additional Resources

- Twisted Documentation: https://docs.twisted.org/
- IPMI Specification: https://www.intel.com/content/www/us/en/products/docs/servers/ipmi/ipmi-home.html
- TFTP RFC: https://tools.ietf.org/html/rfc1350
- `AGENTS.md`: General coding guidelines
- Power driver implementations: `src/provisioningserver/drivers/power/`
