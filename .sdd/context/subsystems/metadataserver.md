# metadataserver Subsystem

## Purpose

Cloud-init metadata service that provides configuration and initialization data to deploying and commissioning machines. This subsystem serves metadata, user-data, and vendor-data to machines during boot, enabling automated configuration and deployment.

**Status**: Active - critical component for machine lifecycle management.

## Location

`src/metadataserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Django**: Web framework for metadata endpoints
- **Cloud-init**: Industry-standard initialization system
- **YAML**: Configuration format for cloud-init

### Key Libraries
- **django**: HTTP endpoints and ORM
- **pyyaml**: YAML processing for cloud-init configs
- **jinja2**: Template rendering for user-data
- **testtools**: Testing framework

## Architectural Constraints

### Django-Based Service

Part of the legacy Django application but serves a distinct purpose:
- Separate URL namespace (`/MAAS/metadata/`)
- Dedicated models for scripts and results
- Integration with machine provisioning workflow

### Machine Lifecycle Integration

Tightly coupled to machine states:
- **Commissioning**: Hardware discovery and inventory
- **Deployment**: OS installation and configuration
- **Testing**: Hardware validation
- **Rescue Mode**: System recovery

### Unauthenticated Access

Metadata endpoints are accessible without authentication:
- Machines authenticate via OAuth tokens embedded in URLs
- Token-based access control per machine
- Limited to specific machine's own metadata

## Key Patterns

### Metadata Endpoint Pattern

Serve cloud-init compatible metadata:

```python
from django.http import HttpResponse
from metadataserver.models import NodeMetadata

def get_metadata(request, version, machine_token):
    """Serve instance metadata."""
    # Validate token
    node = authenticate_machine(machine_token)
    if not node:
        return HttpResponse(status=404)
    
    # Generate metadata
    metadata = {
        'instance-id': node.system_id,
        'local-hostname': node.hostname,
        'public-keys': get_ssh_keys(node),
    }
    
    return HttpResponse(
        yaml.dump(metadata),
        content_type='text/plain'
    )
```

### User-Data Generation

Generate cloud-init user-data scripts:

```python
from metadataserver.user_data import generate_user_data

def get_user_data(request, version, machine_token):
    """Serve cloud-init user-data."""
    node = authenticate_machine(machine_token)
    
    # Generate based on machine state
    if node.status == NODE_STATUS.COMMISSIONING:
        user_data = generate_commissioning_user_data(node)
    elif node.status == NODE_STATUS.DEPLOYING:
        user_data = generate_deployment_user_data(node)
    else:
        user_data = generate_default_user_data(node)
    
    return HttpResponse(user_data, content_type='text/x-shellscript')
```

### Commissioning Scripts

Manage hardware discovery scripts:

```python
from metadataserver.models import Script

class Script(models.Model):
    """Commissioning or testing script."""
    
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField()
    script = models.TextField()
    script_type = models.IntegerField(choices=SCRIPT_TYPE_CHOICES)
    tags = models.ManyToManyField('Tag')
    
    def get_script_for_node(self, node):
        """Render script with node-specific variables."""
        template = Template(self.script)
        return template.render({
            'node': node,
            'system_id': node.system_id,
            'hostname': node.hostname,
        })
```

### Script Results Storage

Store and process commissioning results:

```python
from metadataserver.models import ScriptResult

class ScriptResult(models.Model):
    """Result from running a commissioning/testing script."""
    
    script = models.ForeignKey(Script, on_delete=models.CASCADE)
    script_set = models.ForeignKey('ScriptSet', on_delete=models.CASCADE)
    status = models.IntegerField(default=SCRIPT_STATUS.PENDING)
    exit_status = models.IntegerField(null=True)
    output = models.TextField(blank=True)
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    result = models.TextField(blank=True)
    
    def store_result(self, exit_code, stdout, stderr):
        """Store script execution results."""
        self.exit_status = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.status = (
            SCRIPT_STATUS.PASSED if exit_code == 0 
            else SCRIPT_STATUS.FAILED
        )
        self.save()
        
        # Process results for hardware data
        if self.script.script_type == SCRIPT_TYPE.COMMISSIONING:
            self._process_commissioning_data()
```

### Vendor-Data Pattern

Provide MAAS-specific configuration:

```python
def get_vendor_data(request, version, machine_token):
    """Serve vendor-data for MAAS-specific configuration."""
    node = authenticate_machine(machine_token)
    
    vendor_data = {
        'maas': {
            'metadata_url': get_metadata_url(),
            'signal_url': get_signal_url(node),
            'consumer_key': node.token.consumer.key,
        }
    }
    
    return HttpResponse(
        yaml.dump(vendor_data),
        content_type='text/plain'
    )
```

### Signaling Pattern

Machines signal status back to MAAS:

```python
from metadataserver.api import signal

@api_endpoint
def signal_status(request):
    """Receive status signals from deploying machines."""
    token = request.POST.get('token')
    status = request.POST.get('status')
    message = request.POST.get('message', '')
    
    node = authenticate_machine(token)
    
    # Update node status
    if status == 'OK':
        node.mark_commissioning_complete()
    elif status == 'FAILED':
        node.mark_failed(message)
    elif status == 'WORKING':
        node.update_progress(message)
    
    return {'status': 'acknowledged'}
```

## Testing Requirements

### Test Framework

Follow Django testing patterns:

```python
from maasserver.testing.testcase import MAASServerTestCase
from metadataserver.models import Script, ScriptResult

class TestMetadataEndpoints(MAASServerTestCase):
    """Test metadata service endpoints."""
    
    def test_get_metadata(self):
        """Test retrieving machine metadata."""
        node = self.factory.make_Node()
        token = self.factory.make_NodeToken(node=node)
        
        response = self.client.get(
            f'/MAAS/metadata/latest/meta-data/',
            headers={'Authorization': f'OAuth {token}'}
        )
        
        self.assertEqual(response.status_code, 200)
        metadata = yaml.safe_load(response.content)
        self.assertEqual(metadata['instance-id'], node.system_id)
```

### Script Testing

Test commissioning script execution:

```python
class TestCommissioningScripts(MAASServerTestCase):
    """Test commissioning script functionality."""
    
    def test_run_commissioning_script(self):
        """Test script execution during commissioning."""
        node = self.factory.make_Node(
            status=NODE_STATUS.COMMISSIONING
        )
        script = self.factory.make_Script(
            script_type=SCRIPT_TYPE.COMMISSIONING
        )
        
        # Execute script
        result = run_script(node, script)
        
        # Verify result stored
        self.assertIsNotNone(result.id)
        self.assertEqual(result.script, script)
```

### User-Data Testing

Test cloud-init user-data generation:

```python
class TestUserData(MAASServerTestCase):
    """Test user-data generation."""
    
    def test_commissioning_user_data(self):
        """Test user-data for commissioning."""
        node = self.factory.make_Node(
            status=NODE_STATUS.COMMISSIONING
        )
        
        user_data = generate_commissioning_user_data(node)
        
        # Verify cloud-init format
        self.assertTrue(user_data.startswith('#cloud-config'))
        
        # Parse and validate
        config = yaml.safe_load(user_data)
        self.assertIn('runcmd', config)
```

### Running Tests

```bash
# Run all metadataserver tests
bin/test.region src/metadataserver/

# Run specific test file
bin/test.region src/metadataserver/tests/test_api.py

# Run with coverage
bin/test.region --with-coverage src/metadataserver/
```

## Development Guidelines

### Adding New Scripts

1. **Create Script Model**: Define in database
2. **Implement Script Logic**: Shell or Python
3. **Add Result Processing**: Parse script output
4. **Test Execution**: Verify on test machines
5. **Document Purpose**: Clear script documentation

```python
def create_hardware_info_script():
    """Create script to gather hardware information."""
    script = Script.objects.create(
        name='00-maas-hardware-info',
        description='Gather detailed hardware information',
        script_type=SCRIPT_TYPE.COMMISSIONING,
        script='''#!/bin/bash
lshw -json > hardware.json
lscpu > cpu.txt
free -m > memory.txt
''',
        timeout=300
    )
    return script
```

### Modifying Metadata Format

When changing metadata format:
- Maintain backward compatibility
- Version metadata endpoints
- Update cloud-init templates
- Test with various OS images

### Processing Script Results

Parse and store hardware data from scripts:

```python
def process_lshw_results(script_result):
    """Process lshw hardware detection output."""
    try:
        hardware_data = json.loads(script_result.stdout)
        
        # Extract CPU information
        update_cpu_info(script_result.node, hardware_data)
        
        # Extract memory information
        update_memory_info(script_result.node, hardware_data)
        
        # Extract network interfaces
        update_network_interfaces(script_result.node, hardware_data)
        
        script_result.mark_processed()
    except json.JSONDecodeError as e:
        script_result.mark_failed(f"Invalid JSON: {e}")
```

## Integration Points

### Machine Lifecycle

Integrates with machine status transitions:

```python
# Commissioning start
node.start_commissioning()
# → Metadata service provides commissioning user-data
# → Machine boots and runs scripts
# → Results sent back to metadata service
# → Node marked commissioned

# Deployment start  
node.start_deployment(os_release)
# → Metadata service provides deployment user-data
# → Machine installs OS
# → Configuration applied via cloud-init
# → Node signals completion
```

### MAAS Region Controller

Primary consumer of metadata service:
- Triggers commissioning/deployment
- Receives status signals
- Processes script results
- Updates node state

### MAAS Rack Controller

Provides network connectivity:
- DHCP provides metadata URL to machines
- Proxy for metadata requests
- Boot image serving

### Cloud-Init

Standard cloud initialization:
- Reads metadata on boot
- Executes user-data scripts
- Applies network configuration
- Runs final configuration

### Image Service

Coordinates with image downloads:
- Provides curtin configuration
- OS image selection
- Custom image support

## Common Pitfalls

### Authentication Bypass

❌ **Don't**: Skip token validation
```python
def get_metadata(request):
    # Missing authentication - WRONG!
    node = Node.objects.first()
    return metadata(node)
```

✅ **Do**: Always validate tokens
```python
def get_metadata(request, machine_token):
    node = authenticate_machine(machine_token)
    if not node:
        return HttpResponse(status=404)
    return metadata(node)
```

### Script Timeouts

❌ **Don't**: Infinite script execution
```python
script = Script(timeout=None)  # WRONG!
```

✅ **Do**: Set reasonable timeouts
```python
script = Script(
    timeout=300,  # 5 minutes
    timeout_action=TIMEOUT_ACTION.FAIL
)
```

### Large Script Output

❌ **Don't**: Store unlimited output
```python
result.stdout = script_output  # Could be gigabytes!
```

✅ **Do**: Limit output size
```python
MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10MB

result.stdout = script_output[:MAX_OUTPUT_SIZE]
if len(script_output) > MAX_OUTPUT_SIZE:
    result.note = "Output truncated"
```

### Metadata Caching

❌ **Don't**: Cache metadata indefinitely
```python
@cache_forever
def get_metadata(node):  # WRONG!
    return generate_metadata(node)
```

✅ **Do**: Use appropriate cache duration
```python
@cache(timeout=60)  # 1 minute cache
def get_metadata(node):
    return generate_metadata(node)
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **Cloud-Init**: Cloud initialization patterns
- **YAML Processing**: Configuration file handling
- **Shell Scripting**: Commissioning script development
- **Django Development**: Django-specific patterns
- **Hardware Detection**: System information gathering
- **API Development**: Metadata endpoint design

## Security Considerations

### Token-Based Authentication

Each machine receives unique token:
- Single-use or time-limited tokens
- Token tied to specific machine
- Cannot access other machines' data
- Token invalidated after use

### Script Sandboxing

Commissioning scripts run in controlled environment:
- Limited network access
- No access to MAAS internals
- Timeout enforcement
- Output size limits

### Input Validation

Validate all data from machines:
- Sanitize script results
- Limit upload sizes
- Validate data formats
- Prevent injection attacks

### Secrets Management

Handle sensitive data carefully:
- Don't expose API credentials in user-data
- Use secure token generation
- Rotate tokens regularly
- Encrypt sensitive metadata

## Performance Considerations

### Metadata Caching

Cache generated metadata:
- Short TTL for dynamic data
- Longer TTL for static data
- Invalidate on node changes
- Per-machine cache keys

### Script Parallelization

Run scripts concurrently when possible:
- Independent scripts in parallel
- Respect dependencies
- Limit concurrent executions
- Monitor resource usage

### Result Storage

Optimize result storage:
- Compress large outputs
- Archive old results
- Index for quick queries
- Purge after retention period

### Endpoint Optimization

Optimize metadata endpoints:
- Minimize database queries
- Use select_related/prefetch_related
- Cache template rendering
- Compress responses

## Documentation

### Script Documentation

Document all commissioning scripts:
- Purpose and functionality
- Required permissions
- Expected output format
- Failure conditions
- Timeout settings

### Metadata Format

Document metadata structure:
- Cloud-init compatibility
- MAAS-specific extensions
- Version differences
- Example outputs

### API Endpoints

Document metadata API:
- Endpoint URLs
- Authentication method
- Response formats
- Error conditions

## Additional Resources

- Cloud-Init Documentation: https://cloudinit.readthedocs.io/
- Cloud-Init Spec: https://github.com/canonical/cloud-init
- MAAS Metadata API: https://maas.io/docs/metadata-api
- `AGENTS.md`: General coding guidelines
- `src/maasserver`: Related region controller code