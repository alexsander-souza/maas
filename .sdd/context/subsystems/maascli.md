# maascli Subsystem

## Purpose

Command-line interface for MAAS that provides a comprehensive CLI tool for managing and interacting with MAAS deployments. This subsystem enables users and scripts to perform all MAAS operations from the command line, serving as an alternative to the web UI and a foundation for automation.

**Status**: Active - primary CLI tool for MAAS.

## Location

`src/maascli`

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **argparse**: Command-line argument parsing
- **API Client**: MAAS API client library

### Key Libraries
- **argparse**: CLI argument parsing
- **colorama**: Terminal color output
- **requests**: HTTP client for API communication
- **json**: Data serialization
- **yaml**: Configuration file handling

## Architectural Constraints

### API-Driven Design

The CLI is a thin client that communicates exclusively with the MAAS API:
- No direct database access
- All operations via REST API
- OAuth authentication
- Stateless operation

### User Experience Focus

Designed for both interactive and scripted use:
- Clear, actionable error messages
- Human-readable output by default
- Machine-readable output available (JSON, YAML)
- Progress indicators for long operations
- Helpful usage documentation

### Profile-Based Configuration

Supports multiple MAAS profiles:
- Store multiple server configurations
- Switch between environments easily
- Secure credential storage
- Per-profile settings

## Key Patterns

### Command Structure

Hierarchical command organization:

```python
from maascli.command import Command

class MachinesCommand(Command):
    """Manage machines in MAAS."""
    
    subcommands = {
        'list': ListMachinesCommand,
        'read': ReadMachineCommand,
        'create': CreateMachineCommand,
        'update': UpdateMachineCommand,
        'delete': DeleteMachineCommand,
        'deploy': DeployMachineCommand,
        'release': ReleaseMachineCommand,
    }
```

### Argument Parsing

Structured argument parsing with validation:

```python
from argparse import ArgumentParser

class DeployMachineCommand(Command):
    """Deploy a machine."""
    
    def add_arguments(self, parser: ArgumentParser):
        """Add command-specific arguments."""
        parser.add_argument(
            'system_id',
            help='System ID of the machine to deploy'
        )
        parser.add_argument(
            '--os',
            required=True,
            help='Operating system to deploy'
        )
        parser.add_argument(
            '--distro-series',
            required=True,
            help='Distribution series (e.g., jammy, focal)'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Wait for deployment to complete'
        )
    
    def validate_arguments(self, args):
        """Validate arguments before execution."""
        if not args.system_id:
            raise ValueError("system_id is required")
        
        if not self._is_valid_system_id(args.system_id):
            raise ValueError(f"Invalid system_id format: {args.system_id}")
    
    def execute(self, args):
        """Execute the command."""
        self.validate_arguments(args)
        
        client = self.get_client()
        machine = client.machines.deploy(
            system_id=args.system_id,
            os=args.os,
            distro_series=args.distro_series
        )
        
        self.print_result(machine)
        
        if args.wait:
            self.wait_for_deployment(machine)
```

### Error Handling

User-friendly error messages:

```python
class CommandError(Exception):
    """User-facing command error."""
    pass

def execute_command(command, args):
    """Execute command with error handling."""
    try:
        return command.execute(args)
    except APIError as e:
        # API errors
        if e.status_code == 404:
            raise CommandError(f"Resource not found: {e.detail}")
        elif e.status_code == 401:
            raise CommandError("Authentication failed. Check your credentials.")
        elif e.status_code == 403:
            raise CommandError("Permission denied. Insufficient privileges.")
        else:
            raise CommandError(f"API error: {e.detail}")
    except ConnectionError as e:
        raise CommandError(f"Cannot connect to MAAS server: {e}")
    except ValueError as e:
        raise CommandError(f"Invalid input: {e}")
    except Exception as e:
        # Unexpected errors
        log_error(e)
        raise CommandError(f"Unexpected error: {e}")
```

### Output Formatting

Multiple output formats for different use cases:

```python
from enum import Enum
import json
import yaml

class OutputFormat(Enum):
    """Supported output formats."""
    HUMAN = "human"
    JSON = "json"
    YAML = "yaml"
    TABLE = "table"

class OutputFormatter:
    """Format command output."""
    
    def format(self, data, format: OutputFormat):
        """Format data according to specified format."""
        if format == OutputFormat.JSON:
            return json.dumps(data, indent=2)
        elif format == OutputFormat.YAML:
            return yaml.dump(data, default_flow_style=False)
        elif format == OutputFormat.TABLE:
            return self._format_table(data)
        else:
            return self._format_human(data)
    
    def _format_human(self, data):
        """Human-readable format."""
        if isinstance(data, dict):
            lines = []
            for key, value in data.items():
                lines.append(f"{key}: {value}")
            return "\n".join(lines)
        elif isinstance(data, list):
            return "\n".join(str(item) for item in data)
        else:
            return str(data)
    
    def _format_table(self, data):
        """Tabular format."""
        if not isinstance(data, list) or not data:
            return str(data)
        
        # Extract headers from first item
        headers = list(data[0].keys())
        
        # Calculate column widths
        widths = {h: len(h) for h in headers}
        for item in data:
            for header in headers:
                widths[header] = max(widths[header], len(str(item.get(header, ''))))
        
        # Build table
        lines = []
        
        # Header row
        header_row = " | ".join(h.ljust(widths[h]) for h in headers)
        lines.append(header_row)
        lines.append("-" * len(header_row))
        
        # Data rows
        for item in data:
            row = " | ".join(str(item.get(h, '')).ljust(widths[h]) for h in headers)
            lines.append(row)
        
        return "\n".join(lines)
```

### Profile Management

Manage multiple MAAS server profiles:

```python
import os
import json
from pathlib import Path

class ProfileManager:
    """Manage MAAS CLI profiles."""
    
    def __init__(self):
        self.config_dir = Path.home() / '.maas'
        self.config_file = self.config_dir / 'profiles.json'
        self._ensure_config_dir()
    
    def _ensure_config_dir(self):
        """Ensure configuration directory exists."""
        self.config_dir.mkdir(mode=0o700, exist_ok=True)
    
    def add_profile(self, name: str, url: str, apikey: str):
        """Add a new profile."""
        profiles = self.load_profiles()
        
        profiles[name] = {
            'url': url,
            'apikey': apikey,
        }
        
        self.save_profiles(profiles)
    
    def get_profile(self, name: str = None):
        """Get profile by name or default."""
        profiles = self.load_profiles()
        
        if name:
            if name not in profiles:
                raise ValueError(f"Profile '{name}' not found")
            return profiles[name]
        
        # Return default profile
        default = profiles.get('_default')
        if not default:
            raise ValueError("No default profile set")
        
        return profiles[default]
    
    def set_default(self, name: str):
        """Set default profile."""
        profiles = self.load_profiles()
        
        if name not in profiles:
            raise ValueError(f"Profile '{name}' not found")
        
        profiles['_default'] = name
        self.save_profiles(profiles)
    
    def list_profiles(self):
        """List all profiles."""
        profiles = self.load_profiles()
        default = profiles.get('_default')
        
        result = []
        for name, config in profiles.items():
            if name.startswith('_'):
                continue
            
            result.append({
                'name': name,
                'url': config['url'],
                'default': name == default,
            })
        
        return result
    
    def load_profiles(self):
        """Load profiles from disk."""
        if not self.config_file.exists():
            return {}
        
        with open(self.config_file, 'r') as f:
            return json.load(f)
    
    def save_profiles(self, profiles):
        """Save profiles to disk."""
        with open(self.config_file, 'w') as f:
            json.dump(profiles, f, indent=2)
        
        # Secure permissions
        os.chmod(self.config_file, 0o600)
```

### Interactive Prompts

Prompt for confirmation on destructive operations:

```python
def confirm_action(message: str, default: bool = False) -> bool:
    """Prompt user for confirmation."""
    default_str = "Y/n" if default else "y/N"
    response = input(f"{message} [{default_str}]: ").strip().lower()
    
    if not response:
        return default
    
    return response in ('y', 'yes')

class DeleteMachineCommand(Command):
    """Delete a machine."""
    
    def execute(self, args):
        """Execute the delete command."""
        machine = self.get_machine(args.system_id)
        
        # Prompt for confirmation unless --force
        if not args.force:
            message = f"Delete machine '{machine['hostname']}' ({args.system_id})?"
            if not confirm_action(message, default=False):
                print("Operation cancelled.")
                return
        
        # Perform deletion
        self.client.machines.delete(args.system_id)
        print(f"Machine {args.system_id} deleted successfully.")
```

## Testing Requirements

### Test Framework

Use pytest for CLI testing:

```python
import pytest
from unittest.mock import Mock, patch
from maascli.commands.machines import DeployMachineCommand

class TestDeployMachineCommand:
    """Test machine deployment command."""
    
    def test_deploy_success(self, mocker):
        """Test successful machine deployment."""
        # Mock API client
        mock_client = mocker.Mock()
        mock_client.machines.deploy.return_value = {
            'system_id': 'abc123',
            'hostname': 'machine-1',
            'status_name': 'Deploying'
        }
        
        # Create command
        command = DeployMachineCommand()
        command.get_client = lambda: mock_client
        
        # Execute
        args = mocker.Mock()
        args.system_id = 'abc123'
        args.os = 'ubuntu'
        args.distro_series = 'jammy'
        args.wait = False
        
        command.execute(args)
        
        # Verify
        mock_client.machines.deploy.assert_called_once_with(
            system_id='abc123',
            os='ubuntu',
            distro_series='jammy'
        )
    
    def test_deploy_invalid_system_id(self):
        """Test deployment with invalid system ID."""
        command = DeployMachineCommand()
        
        args = Mock()
        args.system_id = ''
        
        with pytest.raises(ValueError):
            command.validate_arguments(args)
```

### Integration Tests

Test against real MAAS API:

```python
@pytest.mark.integration
class TestCLIIntegration:
    """Integration tests for CLI."""
    
    def test_list_machines(self, maas_client):
        """Test listing machines via CLI."""
        # Requires real MAAS instance
        result = subprocess.run(
            ['maas', 'admin', 'machines', 'read'],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        machines = json.loads(result.stdout)
        assert isinstance(machines, list)
```

### Running Tests

```bash
# Run all CLI tests
pytest src/maascli/tests/

# Run specific test file
pytest src/maascli/tests/test_machines.py

# Run integration tests (requires MAAS)
pytest -m integration src/maascli/tests/

# Run with coverage
pytest --cov=maascli src/maascli/tests/
```

## Development Guidelines

### Adding New Commands

1. **Create Command Class**: Extend base `Command` class
2. **Define Arguments**: Add argument parser configuration
3. **Implement Validation**: Validate inputs early
4. **Execute Logic**: Call API client methods
5. **Format Output**: Use appropriate output formatter
6. **Write Tests**: Unit and integration tests
7. **Update Documentation**: Command help and docs

### Input Validation

**Always validate inputs before API calls**:

```python
def validate_arguments(self, args):
    """Validate command arguments."""
    # Check required fields
    if not args.system_id:
        raise ValueError("system_id is required")
    
    # Validate formats
    if not re.match(r'^[a-z0-9]+$', args.system_id):
        raise ValueError("Invalid system_id format")
    
    # Validate values
    if args.count and args.count < 1:
        raise ValueError("count must be positive")
    
    # Check dependencies
    if args.network_config and not args.deploy:
        raise ValueError("--network-config requires --deploy")
```

### Error Messages

Write clear, actionable error messages:

```python
# ❌ Bad
raise CommandError("Error")

# ✅ Good
raise CommandError(
    "Machine 'abc123' not found. "
    "Use 'maas machines list' to see available machines."
)

# ❌ Bad
raise CommandError("Invalid input")

# ✅ Good
raise CommandError(
    "Invalid OS selection 'windoze'. "
    "Available options: ubuntu, centos, rhel. "
    "Use 'maas os list' to see all options."
)
```

### Help Documentation

Provide comprehensive help text:

```python
class DeployMachineCommand(Command):
    """
    Deploy a machine with the specified operating system.
    
    This command initiates the deployment process for a machine,
    installing the selected operating system and configuring it
    according to the provided parameters.
    
    Examples:
        # Deploy Ubuntu Jammy
        maas admin machine deploy abc123 --os ubuntu --distro-series jammy
        
        # Deploy and wait for completion
        maas admin machine deploy abc123 --os ubuntu --distro-series jammy --wait
        
        # Deploy with custom user data
        maas admin machine deploy abc123 --os ubuntu --distro-series jammy \\
            --user-data @/path/to/cloud-config.yaml
    """
    
    def add_arguments(self, parser):
        """Add command arguments with detailed help."""
        parser.add_argument(
            'system_id',
            help='System ID of the machine to deploy (e.g., abc123)'
        )
        parser.add_argument(
            '--os',
            required=True,
            help='Operating system to install (e.g., ubuntu, centos)'
        )
        parser.add_argument(
            '--distro-series',
            required=True,
            help='Distribution series/version (e.g., jammy, focal, stream8)'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Wait for deployment to complete before returning'
        )
```

## Integration Points

### MAAS API (v2 or v3)

Primary interface to MAAS:
- REST API calls for all operations
- OAuth authentication
- JSON request/response handling
- Error response processing

### API Client Library

Uses `src/apiclient` for API communication:
- HTTP client wrapper
- Authentication handling
- Request serialization
- Response deserialization

### Configuration Files

Reads configuration from:
- `~/.maas/profiles.json`: Profile storage
- Environment variables: `MAAS_URL`, `MAAS_API_KEY`
- Command-line flags: Override defaults

### Shell Integration

Integrates with shell environments:
- Bash completion scripts
- Exit codes for scripting
- Standard input/output handling
- Environment variable support

## Common Pitfalls

### Exposing Credentials

❌ **Don't**: Display API keys in output
```python
print(f"Using API key: {apikey}")  # WRONG!
```

✅ **Do**: Mask sensitive data
```python
masked_key = apikey[:8] + "..." + apikey[-4:]
print(f"Using API key: {masked_key}")
```

### Unclear Error Messages

❌ **Don't**: Generic errors
```python
except Exception as e:
    print(f"Error: {e}")  # Not helpful
```

✅ **Do**: Actionable messages
```python
except ConnectionError:
    print(
        "Error: Cannot connect to MAAS server.\n"
        "Check that the server URL is correct and the server is running.\n"
        f"Current URL: {client.url}"
    )
```

### Missing Input Validation

❌ **Don't**: Skip validation
```python
def execute(self, args):
    # Direct API call without validation
    client.machines.deploy(args.system_id)
```

✅ **Do**: Validate early
```python
def execute(self, args):
    self.validate_arguments(args)
    client.machines.deploy(args.system_id)
```

## Related Skills

Links to relevant skills in `.sdd/skills/`:

- **CLI Development**: Command-line interface design
- **Python Development**: General Python patterns
- **API Client**: REST API client implementation
- **User Experience**: CLI UX best practices
- **Error Handling**: User-friendly error messages
- **Testing**: CLI testing strategies

## Security Considerations

### Credential Storage

Secure storage of API credentials:
- File permissions: 0600 for config files
- No plaintext passwords in scripts
- Use system keyring when available
- Prompt for credentials when needed

### Input Sanitization

Sanitize all user inputs:
- Validate formats before API calls
- Prevent command injection
- Escape special characters
- Validate file paths

### API Key Handling

Protect API keys:
- Never log API keys
- Don't include in error messages
- Clear from memory after use
- Rotate keys regularly

## Performance Considerations

### Caching

Cache API responses when appropriate:
- OS image lists
- Profile data
- Server capabilities

### Batch Operations

Support batch operations:
- Deploy multiple machines
- Bulk updates
- Parallel API calls when safe

### Progress Indicators

Show progress for long operations:
- Deployment status
- Image downloads
- Bulk operations

## Documentation

### Command Help

All commands must have:
- Brief description
- Detailed explanation
- Usage examples
- Argument descriptions
- Common error solutions

### Man Pages

Generate man pages from help:
- Standard Unix format
- Organized by category
- Cross-references
- Examples section

### Online Documentation

Link to comprehensive docs:
- API reference
- Tutorials
- Troubleshooting guides
- Best practices

## Additional Resources

- argparse Documentation: https://docs.python.org/3/library/argparse.html
- Click Framework: https://click.palletsprojects.com/ (alternative)
- CLI Guidelines: https://clig.dev/
- `AGENTS.md`: General coding guidelines
- `src/apiclient`: API client library