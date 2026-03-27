# metadataserver Subsystem

## Purpose

Metadata service providing cloud-init and curtin configuration data to machines during deployment and commissioning. This Django-based subsystem serves machine-specific configuration via HTTP endpoints, enabling automated OS installation and initial configuration.

**Status**: Active - critical for machine deployment.

## Location

`src/metadataserver`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Django**: Web framework
- **cloud-init**: Cloud instance initialization
- **curtin**: OS installation tool

### Key Libraries
- **django**: Web framework
- **pyyaml**: Configuration serialization
- **jinja2**: Template rendering
- **requests**: HTTP client for testing

## Architectural Constraints

### Django Integration

Built as a Django app within maasserver:
- Uses Django models and ORM
- HTTP endpoints via Django views
- Authentication via Django middleware
- Integrated with maasserver database

### Stateless Endpoints

All endpoints are stateless:
- No session storage
- Configuration generated on-demand
- Token-based authentication
- RESTful design

### Security-Critical

Serves sensitive configuration data:
- Machine credentials
- Network configuration
- User data and scripts
- API keys and tokens

Must validate all requests and authorize access.

## Key Patterns

> **See**: [django-patterns.md](../../skills/languages/django-patterns.md) for Django-specific patterns.

### Metadata Endpoint Pattern

Serve metadata to machines via HTTP:

```python
from django.http import JsonResponse, HttpResponse
from metadataserver.models import NodeMetadata

def get_metadata(request, system_id, token):
    """Get metadata for machine."""
    # Validate token
    metadata = NodeMetadata.objects.get(
        node__system_id=system_id,
        token=token
    )
    
    if not metadata.is_valid():
        return HttpResponse("Invalid token", status=403)
    
    # Generate metadata
    data = {
        'instance-id': metadata.node.system_id,
        'local-hostname': metadata.node.hostname,
        'public-keys': metadata.get_public_keys(),
        'network-config': metadata.get_network_config(),
    }
    
    return JsonResponse(data)
```

### Cloud-Init Configuration

Generate cloud-init user-data:

```python
def get_cloud_init_userdata(node, preseed_type):
    """Generate cloud-init user-data for node."""
    template = get_preseed_template(preseed_type)
    
    context = {
        'node': node,
        'hostname': node.hostname,
        'fqdn': node.fqdn,
        'preseed_data': get_preseed_data(node),
        'ssh_keys': get_authorized_keys(node),
        'packages': get_required_packages(node),
    }
    
    return template.render(context)
```

### Curtin Configuration

Generate curtin installation config:

```python
def get_curtin_config(node):
    """Generate curtin configuration for installation."""
    config = {
        'install': {
            'target': '/target',
            'unmount': 'disabled',
        },
        'partitioning': get_partition_layout(node),
        'network': get_network_config(node),
        'sources': {
            '00_primary': {
                'uri': get_image_url(node),
                'type': 'tgz',
            }
        },
        'late_commands': get_late_commands(node),
    }
    
    return config

def get_partition_layout(node):
    """Generate partition layout for node."""
    disks = node.physicalblockdevice_set.all()
    
    layout = []
    for disk in disks:
        layout.append({
            'id': f'disk-{disk.id}',
            'type': 'disk',
            'path': disk.path,
            'ptable': 'gpt',
            'partitions': get_disk_partitions(disk)
        })
    
    return layout
```

### Token-Based Authentication

Secure metadata access with tokens:

```python
from django.utils.crypto import get_random_string
from metadataserver.models import NodeKey

def create_metadata_token(node):
    """Create secure token for metadata access."""
    token = get_random_string(32)
    
    NodeKey.objects.create(
        node=node,
        token=token,
        key_type='metadata',
        valid_until=timezone.now() + timedelta(hours=24)
    )
    
    return token

def validate_metadata_token(system_id, token):
    """Validate metadata token."""
    try:
        key = NodeKey.objects.get(
            node__system_id=system_id,
            token=token,
            key_type='metadata'
        )
        
        if key.valid_until < timezone.now():
            key.delete()
            return False
        
        return True
    except NodeKey.DoesNotExist:
        return False
```

### Preseed Template Pattern

Template-based configuration generation:

```python
from django.template import Template, Context

def render_preseed(node, template_name):
    """Render preseed template for node."""
    template_path = f'preseeds/{template_name}.template'
    template_content = load_template(template_path)
    
    template = Template(template_content)
    context = Context({
        'node': node,
        'main_archive': get_main_archive_url(),
        'kernel_opts': get_kernel_options(node),
        'preseed_data': get_preseed_data(node),
    })
    
    return template.render(context)
```

## Testing Requirements

> **See**: [test-code-quality.md](../../skills/techniques/test-code-quality.md) for comprehensive testing patterns.

### Test Metadata Endpoints

Test all metadata endpoints:

```python
from django.test import TestCase, Client
from maasserver.testing.factory import factory

class TestMetadataEndpoints(TestCase):
    """Test metadata HTTP endpoints."""
    
    def test_get_metadata_with_valid_token(self):
        """Test metadata endpoint with valid token."""
        node = factory.make_Node()
        token = create_metadata_token(node)
        
        client = Client()
        response = client.get(
            f'/metadata/{node.system_id}/{token}/'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['instance-id'], node.system_id)
    
    def test_get_metadata_with_invalid_token(self):
        """Test metadata endpoint with invalid token."""
        node = factory.make_Node()
        
        client = Client()
        response = client.get(
            f'/metadata/{node.system_id}/invalid-token/'
        )
        
        self.assertEqual(response.status_code, 403)
```

### Test Configuration Generation

Test configuration generation logic:

```python
class TestCurtinConfig(TestCase):
    """Test curtin configuration generation."""
    
    def test_generate_curtin_config(self):
        """Test generating curtin config."""
        node = factory.make_Node_with_Interface_on_Subnet()
        factory.make_PhysicalBlockDevice(node=node)
        
        config = get_curtin_config(node)
        
        self.assertIn('install', config)
        self.assertIn('partitioning', config)
        self.assertIn('network', config)
        self.assertTrue(len(config['partitioning']) > 0)
```

### Running Tests

```bash
# All metadataserver tests
pytest src/metadataserver/tests/

# Specific test module
pytest src/metadataserver/tests/test_api.py

# With coverage
pytest --cov=metadataserver src/metadataserver/tests/
```

## Development Guidelines

### Adding New Endpoints

1. Define URL pattern in `urls.py`
2. Implement view function with token validation
3. Generate appropriate configuration
4. Test with valid and invalid tokens
5. Document endpoint in API docs

### Security First

All endpoints must:
- Validate authentication tokens
- Check token expiration
- Log access attempts
- Sanitize all inputs
- Never expose sensitive data in errors

### Configuration Generation

Follow these principles:
- Generate config on-demand (don't cache)
- Validate node state before generation
- Use templates for complex configs
- Include error recovery mechanisms
- Log generation for debugging

### Template Management

```python
def get_preseed_template(name):
    """Get preseed template by name."""
    template_path = os.path.join(PRESEED_DIR, f'{name}.template')
    
    if not os.path.exists(template_path):
        raise TemplateNotFound(f"Template {name} not found")
    
    with open(template_path, 'r') as f:
        return f.read()
```

## Integration Points

### Machine Deployment Flow
1. Machine powers on and boots PXE
2. Bootloader requests metadata URL with token
3. Machine downloads cloud-init config
4. Machine downloads curtin config
5. Curtin installs OS using config
6. Cloud-init configures instance
7. Machine reports completion

### MAAS Server (maasserver)
- Uses Django models from maasserver
- Shares authentication system
- Access to node configuration
- See [maasserver.md](./maasserver.md)

### Rack Controller (provisioningserver)
- Rack serves metadata endpoints as proxy
- Caches metadata for performance
- Handles TFTP/HTTP boot process
- See [provisioningserver.md](./provisioningserver.md)

### Cloud-Init
- Reads instance-id, hostname, keys
- Applies network configuration
- Runs user-provided scripts
- Reports deployment status

### Curtin
- Performs OS installation
- Partitions disks
- Configures storage
- Installs bootloader

## Common Pitfalls

> **See**: [common-anti-patterns.md](../../common-anti-patterns.md) for general anti-patterns.

### Exposing Sensitive Data

❌ **Don't** include secrets in metadata responses:
```python
# WRONG!
def get_metadata(request, system_id, token):
    return JsonResponse({
        'hostname': node.hostname,
        'api_key': node.owner.api_key,  # WRONG! Never expose
        'password': node.password,  # WRONG!
    })
```

✅ **Do** only include necessary data:
```python
# Correct
def get_metadata(request, system_id, token):
    return JsonResponse({
        'instance-id': node.system_id,
        'local-hostname': node.hostname,
        'public-keys': get_authorized_keys(node),  # Public keys only
    })
```

### Token Validation Bypass

❌ **Don't** skip token validation:
```python
# WRONG!
def get_metadata(request, system_id, token):
    node = Node.objects.get(system_id=system_id)  # No validation!
    return JsonResponse(get_metadata_dict(node))
```

✅ **Do** always validate tokens:
```python
# Correct
def get_metadata(request, system_id, token):
    if not validate_metadata_token(system_id, token):
        return HttpResponse("Unauthorized", status=403)
    
    node = Node.objects.get(system_id=system_id)
    return JsonResponse(get_metadata_dict(node))
```

### Caching Metadata

❌ **Don't** cache generated metadata:
```python
# WRONG!
cached_metadata = {}

def get_metadata(request, system_id, token):
    if system_id in cached_metadata:
        return JsonResponse(cached_metadata[system_id])  # Stale!
    
    metadata = generate_metadata(system_id)
    cached_metadata[system_id] = metadata
    return JsonResponse(metadata)
```

✅ **Do** generate fresh metadata:
```python
# Correct
def get_metadata(request, system_id, token):
    # Always generate fresh metadata
    metadata = generate_metadata(system_id)
    return JsonResponse(metadata)
```

## Security Considerations

> **See**: [security-practices.md](../../skills/techniques/security-practices.md)

### Token Management
- Generate cryptographically secure tokens
- Set appropriate expiration times
- Single-use tokens for sensitive operations
- Rotate tokens on security events

### Access Control
- Validate all tokens before serving data
- Log all metadata requests
- Rate limit requests per token
- Detect and block suspicious patterns

### Data Protection
- Never include passwords or API keys
- Use public keys only for SSH access
- Sanitize all user-provided data
- Validate configuration before serving

### Audit Logging
- Log all metadata requests with timestamps
- Track token usage and validation failures
- Alert on suspicious access patterns
- Retain logs for security audits

## Performance Considerations

### Configuration Generation
- Generate configs on-demand (don't pre-generate)
- Use efficient template rendering
- Minimize database queries
- Cache static data (templates, images)

### HTTP Response Times
- Keep metadata responses under 100ms
- Use connection pooling
- Minimize serialization overhead
- Compress large responses

### Database Queries
- Use select_related for foreign keys
- Prefetch related objects when needed
- Index frequently queried fields
- Avoid N+1 query problems

## Additional Resources

- **Cloud-Init Documentation**: https://cloudinit.readthedocs.io/
- **Curtin Documentation**: https://curtin.readthedocs.io/
- **EC2 Metadata API**: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html
- **Related**: [django-patterns.md](../../skills/languages/django-patterns.md), [maasserver.md](./maasserver.md)